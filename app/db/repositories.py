"""Репозиторий задач."""
import logging

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task, TaskStatus

logger = logging.getLogger(__name__)

class TaskRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, task: Task) -> Task:
        self.session.add(task)
        try:
            await self.session.commit()
        except IntegrityError:
            # Срабатывает при гонке данных:
            # Откатываем неудачную транзакцию;
            # вызывающий код (роутер) заново ищет задачу по хэшу и возвращает её как deduplicated=true.
            await self.session.rollback()
            logger.info(
                "race on archive_sha256=%s: concurrent insert lost, "
                "falling back to dedup lookup",
                task.archive_sha256,
            )
            raise
        await self.session.refresh(task)
        return task

    async def get(self, task_id: str) -> Task | None:
        return await self.session.get(Task, task_id)

    async def list_all(self) -> list[Task]:
        res = await self.session.execute(select(Task))
        return list(res.scalars().all())

    async def get_by_hash(self, archive_sha256: str) -> Task | None:
        """Ищет активную (не ERROR, dedup_eligible) задачу с данным хэшем."""
        res = await self.session.execute(
            select(Task).where(
                Task.archive_sha256 == archive_sha256,
                Task.status != TaskStatus.ERROR,
                Task.dedup_eligible == True,
            )
        )
        return res.scalars().first()

    async def increment_dedup_hit(self, task_id: str) -> None:
        """Атомарно увеличивает счётчик дедуп-попаданий для задачи в БД."""
        await self.session.execute(
            text("UPDATE tasks SET dedup_hit_count = dedup_hit_count + 1 WHERE id = :id"),
            {"id": task_id},
        )
        await self.session.commit()

    async def get_stats(self) -> dict:
        """Агрегаты по задачам одним SQL-запросом (агрегация в БД).

        CTE-запрос с четырьмя скалярными подзапросами в одном SELECT:
          - total_tasks: COUNT(*) всех задач
          - by_status_json: GROUP BY status → json_group_object (агрегат в БД)
          - avg/median processing seconds для DONE-задач (median через
            ROW_NUMBER() OVER ORDER BY + выбор центрального элемента)
          - deduplicated_count: SUM(dedup_hit_count) — персистентный счётчик,
            инкрементируемый атомарным UPDATE в момент обнаружения дубликата
        """
        sql = text(
            """
            WITH status_counts AS (
                SELECT status, COUNT(*) AS cnt
                FROM tasks
                GROUP BY status
            ),
            durations AS (
                SELECT
                    (julianday(finished_at) - julianday(created_at)) * 86400.0 AS secs
                FROM tasks
                WHERE status = 'DONE' AND finished_at IS NOT NULL
            ),
            duration_stats AS (
                SELECT AVG(secs) AS avg_secs, COUNT(*) AS n
                FROM durations
            ),
            ordered AS (
                SELECT secs, ROW_NUMBER() OVER (ORDER BY secs) AS rn
                FROM durations
            ),
            median_calc AS (
                SELECT AVG(secs) AS median_secs
                FROM ordered, duration_stats
                WHERE rn IN (
                    (duration_stats.n + 1) / 2,
                    (duration_stats.n + 2) / 2
                )
            )
            SELECT
                (SELECT COUNT(*) FROM tasks) AS total_tasks,
                (SELECT json_group_object(status, cnt) FROM status_counts) AS by_status_json,
                (SELECT avg_secs FROM duration_stats) AS avg_processing_seconds,
                (SELECT median_secs FROM median_calc) AS median_processing_seconds,
                (SELECT COALESCE(SUM(dedup_hit_count), 0) FROM tasks) AS deduplicated_count
            """
        )
        res = await self.session.execute(sql)
        row = res.mappings().one()
        return dict(row)
