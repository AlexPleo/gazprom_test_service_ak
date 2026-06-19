"""
Модель задачи обработки. Для простоты запуска используется sqlite; в продакшене
здесь был бы PostgreSQL (SQLAlchemy 2.0 async это поддерживает без изменений модели).
"""
import enum
from datetime import datetime

from sqlalchemy import String, DateTime, Enum, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # TODO(кандидат): добавить поле с хэшем содержимого архива для дедупликации.
    # archive_sha256: Mapped[str | None] = ...
