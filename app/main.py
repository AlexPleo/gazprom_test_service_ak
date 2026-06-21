"""Точка входа приложения."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.engine import init_db
from app.routers.upload import router as upload_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Document processing — backend", lifespan=lifespan)
app.include_router(upload_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
