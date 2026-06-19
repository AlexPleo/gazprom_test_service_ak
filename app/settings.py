from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    CHUNK_SIZE: int

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'


settings = Settings()
