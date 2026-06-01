import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"필수 환경변수 '{key}'가 설정되지 않았습니다. .env 파일을 확인하세요.")
    return value


POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "action_recommend")
POSTGRES_USER = _require("POSTGRES_USER")
POSTGRES_PASSWORD = _require("POSTGRES_PASSWORD")

DATABASE_URL = (
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

LLM_MODE = os.getenv("LLM_MODE", "mock")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
