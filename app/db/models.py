"""
Модель задачи обработки. Для простоты запуска используется sqlite; в продакшене
здесь был бы PostgreSQL (SQLAlchemy 2.0 async это поддерживает без изменений модели).
"""
import enum
from datetime import datetime

from sqlalchemy import String, DateTime, Enum, Integer, Boolean, Index
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

    archive_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    dedup_hit_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # False для задач, созданных через ?force=true
    dedup_eligible: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    __table_args__ = (
        # Частичный уникальный индекс: не более одной активной (не ERROR,
        # dedup_eligible) задачи на каждый хэш архива.
        Index(
            "uq_tasks_archive_sha256_active",
            "archive_sha256",
            unique=True,
            sqlite_where=(status != TaskStatus.ERROR) & (dedup_eligible == True),
        ),
    )
