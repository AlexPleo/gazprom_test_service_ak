"""Смоук-тест: загрузка создаёт задачу. Тесты на дедуп и /api/stats добавляешь рядом."""
import asyncio
import io

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.db import engine as engine_module
from app.db.models import Base
from app.main import app

@pytest_asyncio.fixture
async def client(tmp_path):
    """Изолированная файловая sqlite БД на каждый тест + переопределённая
    sessionmaker.

    Используем файл (а не in-memory + StaticPool), потому что in-memory
    sqlite через один shared connection не выдерживает настоящую
    конкурентность (несколько корутин не могут одновременно использовать
    одно DBAPI-соединение) и даёт хаотичные ошибки уровня драйвера вместо
    предсказуемого IntegrityError. Файловая БД ближе к реальному
    продакшен-поведению (отдельные соединения из пула на каждый запрос).
    """
    db_path = tmp_path / "test.db"
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    test_session = async_sessionmaker(test_engine, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Подменяем глобальные engine/async_session, которые использует
    # _fake_process (через app.db.engine.async_session) и get_session.
    engine_module.engine = test_engine
    engine_module.async_session = test_session

    async def override_get_session():
        async with test_session() as session:
            yield session

    app.dependency_overrides[engine_module.get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await test_engine.dispose()

async def _wait_processing_done(client: AsyncClient, attempts: int = 20):
    """Ждём, пока фоновая asyncio-задача (_fake_process) завершится."""
    for _ in range(attempts):
        resp = await client.get("/api/stats")
        data = resp.json()
        processing = next(
            (s["count"] for s in data["by_status"] if s["status"] == "PROCESSING"), 0
        )
        if processing == 0:
            return data
        await asyncio.sleep(0.05)
    return data


@pytest.mark.asyncio
async def test_upload_creates_task():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        files = {"file": ("a.zip", io.BytesIO(b"hello"), "application/zip")}
        r = await ac.post("/api/classify-zip/", files=files)
        assert r.status_code == 200
        assert "task_id" in r.json()

@pytest.mark.asyncio
async def test_upload_happy_path(client: AsyncClient):
    """Обычная загрузка создаёт новую задачу и не дедуплицируется на пустом месте."""
    resp = await client.post(
        "/api/classify-zip/",
        files={"file": ("a.zip", b"hello world content", "application/zip")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["deduplicated"] is False
    assert body["task_id"]



@pytest.mark.asyncio
async def test_duplicate_upload_is_deduplicated_and_does_not_create_new_task(
    client: AsyncClient,
):
    """Повторная загрузка того же содержимого возвращает тот же task_id
    с deduplicated=true и не создаёт новую задачу."""
    content = b"identical archive bytes"

    first = await client.post(
        "/api/classify-zip/",
        files={"file": ("a.zip", content, "application/zip")},
    )
    second = await client.post(
        "/api/classify-zip/",
        files={"file": ("a.zip", content, "application/zip")},
    )

    assert first.status_code == 200
    assert second.status_code == 200

    first_body = first.json()
    second_body = second.json()

    assert first_body["deduplicated"] is False
    assert second_body["deduplicated"] is True
    assert second_body["task_id"] == first_body["task_id"]

    stats = await _wait_processing_done(client)
    assert stats["total_tasks"] == 1  # вторая загрузка НЕ создала новую задачу
    assert stats["deduplicated_count"] == 1


@pytest.mark.asyncio
async def test_force_bypasses_dedup_but_plain_retry_still_dedups_to_original(
    client: AsyncClient,
):
    """?force=true создаёт новую задачу, игнорируя дубликат, но последующая
    обычная (не force) загрузка того же файла всё равно дедуплицируется
    к ИСХОДНОЙ задаче, а не к форсированной."""
    content = b"force test content"

    original = await client.post(
        "/api/classify-zip/",
        files={"file": ("a.zip", content, "application/zip")},
    )
    forced = await client.post(
        "/api/classify-zip/?force=true",
        files={"file": ("a.zip", content, "application/zip")},
    )
    plain_again = await client.post(
        "/api/classify-zip/",
        files={"file": ("a.zip", content, "application/zip")},
    )

    original_body = original.json()
    forced_body = forced.json()
    plain_again_body = plain_again.json()

    assert forced_body["deduplicated"] is False
    assert forced_body["task_id"] != original_body["task_id"]

    assert plain_again_body["deduplicated"] is True
    assert plain_again_body["task_id"] == original_body["task_id"]

    stats = await _wait_processing_done(client)
    assert stats["total_tasks"] == 2  # original + forced, plain_again не создал новую


@pytest.mark.asyncio
async def test_concurrent_uploads_of_same_archive_create_only_one_task(client: AsyncClient):
    """Несколько одновременных загрузок одного и того же архива должны
    привести только к одной задаче (защита от race condition через
    частичный уникальный индекс в БД)."""
    content = b"race condition test content"

    responses = await asyncio.gather(
        *[
            client.post(
                "/api/classify-zip/",
                files={"file": ("a.zip", content, "application/zip")},
            )
            for _ in range(5)
        ]
    )

    task_ids = {r.json()["task_id"] for r in responses}
    assert len(task_ids) == 1  # все запросы сошлись к одной задаче

    deduplicated_flags = [r.json()["deduplicated"] for r in responses]
    assert deduplicated_flags.count(False) == 1  # ровно одна "настоящая" загрузка
    assert deduplicated_flags.count(True) == 4

    stats = await _wait_processing_done(client)
    assert stats["total_tasks"] == 1


@pytest.mark.asyncio
async def test_stats_endpoint_shape_and_aggregates(client: AsyncClient):
    """/api/stats возвращает корректную структуру и агрегаты."""
    await client.post(
        "/api/classify-zip/",
        files={"file": ("a.zip", b"content A", "application/zip")},
    )
    await client.post(
        "/api/classify-zip/",
        files={"file": ("b.zip", b"content B", "application/zip")},
    )
    # дубликат первого
    await client.post(
        "/api/classify-zip/",
        files={"file": ("a.zip", b"content A", "application/zip")},
    )

    stats = await _wait_processing_done(client)

    assert stats["total_tasks"] == 2
    assert stats["deduplicated_count"] == 1
    assert isinstance(stats["by_status"], list)
    statuses = {s["status"] for s in stats["by_status"]}
    assert statuses == {"DONE"}
    done_count = next(s["count"] for s in stats["by_status"] if s["status"] == "DONE")
    assert done_count == 2

    # обе задачи завершились почти мгновенно (имитация sleep(0.1)) —
    # среднее и медиана должны быть положительными числами, не None
    assert stats["avg_processing_seconds"] is not None
    assert stats["avg_processing_seconds"] > 0
    assert stats["median_processing_seconds"] is not None
    assert stats["median_processing_seconds"] > 0


@pytest.mark.asyncio
async def test_stats_on_empty_database_does_not_crash(client: AsyncClient):
    """/api/stats на пустой БД отдаёт нулевые/None агрегаты, а не падает."""
    resp = await client.get("/api/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_tasks"] == 0
    assert body["by_status"] == []
    assert body["avg_processing_seconds"] is None
    assert body["median_processing_seconds"] is None
    assert body["deduplicated_count"] == 0

