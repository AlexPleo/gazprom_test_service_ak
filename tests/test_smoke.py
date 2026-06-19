"""Смоук-тест: загрузка создаёт задачу. Тесты на дедуп и /api/stats добавляешь рядом."""
import io

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_upload_creates_task():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        files = {"file": ("a.zip", io.BytesIO(b"hello"), "application/zip")}
        r = await ac.post("/api/classify-zip/", files=files)
        assert r.status_code == 200
        assert "task_id" in r.json()

    # TODO(кандидат): тест — повторная загрузка того же содержимого не плодит задачу.
    # TODO(кандидат): тест — формат ответа /api/stats.
