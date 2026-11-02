from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CHUNK_SIZE: int = 800
CHUNK_OVERLAP: int = 100
TOP_K_CHUNKS: int = 5
EMBEDDING_DIM: int = 384
MAX_FILE_BYTES: int = 200 * 1024


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://kodgard:kodgard@localhost:5432/kodgard"
    KODGARD_HOME: str = str(PROJECT_ROOT)
    ASSISTANT_MODEL: str = "claude-haiku-5-5"
    EMBEDDING_MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
    HF_HOME: str | None = None
    CHUNK_SIZE: int = CHUNK_SIZE
    CHUNK_OVERLAP: int = CHUNK_OVERLAP
    TOP_K_CHUNKS: int = TOP_K_CHUNKS

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
