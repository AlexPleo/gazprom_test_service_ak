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

    # TODO(кандидат): агрегаты для /api/stats считаем здесь ОДНИМ SQL-запросом,
    # а не выгрузкой всех задач в Python.
