"""Репозиторий задач."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task, TaskStatus


class TaskRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, task: Task) -> Task:
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        return task

    async def get(self, task_id: str) -> Task | None:
        return await self.session.get(Task, task_id)

    async def list_all(self) -> list[Task]:
        res = await self.session.execute(select(Task))
        return list(res.scalars().all())

    # TODO(кандидат): метод поиска задачи по хэшу архива.
    # async def get_by_hash(self, archive_sha256: str) -> Task | None: ...

    # TODO(кандидат): агрегаты для /api/stats считаем здесь ОДНИМ SQL-запросом,
    # а не выгрузкой всех задач в Python.
