"""Pydantic-схемы запросов и ответов API."""
from pydantic import BaseModel, ConfigDict


class UploadResponse(BaseModel):
    """Ответ на загрузку ZIP-архива."""

    task_id: str
    deduplicated: bool


class StatusCount(BaseModel):
    """Количество задач в конкретном статусе."""

    status: str
    count: int


class StatsResponse(BaseModel):
    """Агрегированная статистика по задачам."""

    model_config = ConfigDict(from_attributes=True)

    total_tasks: int
    by_status: list[StatusCount]
    avg_processing_seconds: float | None
    median_processing_seconds: float | None
    deduplicated_count: int
