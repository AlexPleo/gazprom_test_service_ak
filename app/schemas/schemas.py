"""Pydantic-схемы запросов и ответов API."""
from pydantic import BaseModel, ConfigDict


class UploadResponse(BaseModel):
    """Ответ на загрузку ZIP-архива."""

    task_id: str
    deduplicated: bool
