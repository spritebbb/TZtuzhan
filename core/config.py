"""配置加载：从项目根目录 .env 读取，提供全局 Config 对象。"""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    def __init__(self) -> None:
        self.llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
        self.llm_api_key: str = os.getenv("LLM_API_KEY", "")
        self.llm_model: str = os.getenv("LLM_MODEL", "deepseek-chat")
        self.llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.8"))
        self.llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "500"))

        persona = os.getenv("PERSONA_FILE", "../persona-菟菚.md")
        p = Path(persona)
        self.persona_file: Path = p if p.is_absolute() else (PROJECT_ROOT / p)

        self.data_dir: Path = PROJECT_ROOT / "data"


config = Config()
