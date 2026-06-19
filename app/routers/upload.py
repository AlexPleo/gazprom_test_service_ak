"""
Роутер загрузки архива.

Сейчас: каждая загрузка создаёт новую задачу и запускает имитацию обработки.
Задача — добавить идемпотентность по хэшу и эндпоинт /api/stats.
"""
import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import engine as db_engine
from app.db.engine import get_session
from app.db.models import Task, TaskStatus
from app.db.repositories import TaskRepository
from app.settings import settings
from app.schemas.schemas import UploadResponse, StatsResponse, StatusCount

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


async def _fake_process(task_id: str) -> None:
    """Имитация фоновой обработки (в продакшене — Celery / отдельный воркер)."""
    await asyncio.sleep(0.1)  # как будто зовём LLM/OCR — это дорого
    async with db_engine.async_session() as session:
        repo = TaskRepository(session)
        task = await repo.get(task_id)
        if task is None:
            logger.warning("task %s disappeared before processing finished", task_id)
            return
        task.status = TaskStatus.DONE
        task.finished_at = datetime.now()
        await session.commit()
        logger.info("task %s finished processing", task_id)


async def get_file_hash(file: UploadFile) -> str:
    """Вычисляет SHA256 потоково, не загружая файл целиком в RAM."""
    sha256_hash = hashlib.sha256()
    # Читаем файл по CHUNK_SIZE мегабайт за раз
    while chunk := await file.read(settings.CHUNK_SIZE * 1024 * 1024):
        sha256_hash.update(chunk)

    await file.seek(0)
    return sha256_hash.hexdigest()


@router.post("/classify-zip/", response_model=UploadResponse)
async def classify_zip(
        file: UploadFile,
        force: bool = Query(False, description="Обойти дедупликацию по хэшу"),
        session: AsyncSession = Depends(get_session),
):
    repo = TaskRepository(session)
    archive_sha256 = await get_file_hash(file)

    if not force:
        existing = await repo.get_by_hash(archive_sha256)
        if existing is not None:
            logger.info(
                "deduplicated upload: hash=%s -> existing task_id=%s",
                archive_sha256,
                existing.id,
            )
            await repo.increment_dedup_hit(existing.id)
            return UploadResponse(task_id=existing.id, deduplicated=True)

    task = Task(
        id=str(uuid.uuid4()),
        original_filename=file.filename or "archive.zip",
        status=TaskStatus.PROCESSING,
        archive_sha256=archive_sha256,
        dedup_eligible=not force,
    )

    try:
        await repo.create(task)
    except IntegrityError:
        # Race condition: другой конкурентный не-force запрос вставил задачу
        # первым. Частичный уникальный индекс в БД отклонил наш INSERT.
        # repo.create откатил транзакцию — ищем победителя по хэшу и
        # возвращаем его как deduplicated, не запуская лишнюю обработку.
        existing = await repo.get_by_hash(archive_sha256)
        if existing is not None:
            logger.info(
                "race resolved: hash=%s lost insert race, returning task_id=%s",
                archive_sha256,
                existing.id,
            )
            await repo.increment_dedup_hit(existing.id)
            return UploadResponse(task_id=existing.id, deduplicated=True)
        raise

    asyncio.create_task(_fake_process(task.id))
    logger.info("created task_id=%s hash=%s force=%s", task.id, archive_sha256, force)
    return UploadResponse(task_id=task.id, deduplicated=False)


@router.get("/stats", response_model=StatsResponse)
async def get_stats(session: AsyncSession = Depends(get_session)):
    repo = TaskRepository(session)
    row = await repo.get_stats()

    by_status_raw = json.loads(row["by_status_json"]) if row["by_status_json"] else {}
    by_status = [StatusCount(status=s, count=c) for s, c in by_status_raw.items()]

    return StatsResponse(
        total_tasks=row["total_tasks"],
        by_status=by_status,
        avg_processing_seconds=row["avg_processing_seconds"],
        median_processing_seconds=row["median_processing_seconds"],
        deduplicated_count=row["deduplicated_count"],
    )
