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


# TODO(кандидат): тест — формат ответа /api/stats.
