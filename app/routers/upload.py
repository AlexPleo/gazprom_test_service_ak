"""
Роутер загрузки архива.

Сейчас: каждая загрузка создаёт новую задачу и запускает имитацию обработки.
Задача — добавить идемпотентность по хэшу и эндпоинт /api/stats.
"""
import asyncio
import uuid

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.db.models import Task, TaskStatus
from app.db.repositories import TaskRepository

router = APIRouter(prefix="/api")


async def _fake_process(task_id: str) -> None:
    """Имитация фоновой обработки (в продакшене — Celery / отдельный воркер)."""
    await asyncio.sleep(0.1)  # как будто зовём LLM/OCR — это дорого


@router.post("/classify-zip/")
async def classify_zip(file: UploadFile, session: AsyncSession = Depends(get_session)):
    repo = TaskRepository(session)

    content = await file.read()  # noqa: F841 — пригодится для хэша

    # TODO(кандидат): посчитать sha256(content); если задача с таким хэшем уже есть
    #   и не в статусе ERROR — вернуть её task_id с deduplicated=true, не запуская обработку.
    #   Параметр ?force=true должен обходить дедуп.

    task = Task(
        id=str(uuid.uuid4()),
        original_filename=file.filename or "archive.zip",
        status=TaskStatus.PROCESSING,
    )
    await repo.create(task)
    asyncio.create_task(_fake_process(task.id))
    return {"task_id": task.id, "deduplicated": False}


# TODO(кандидат): GET /api/stats — агрегаты по задачам ОДНИМ SQL-запросом.
