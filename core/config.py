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

        persona = os.getenv("PERSONA_FILE", "persona-菟菚.md")
        p = Path(persona)
        self.persona_file: Path = p if p.is_absolute() else (PROJECT_ROOT / p)

        self.data_dir: Path = PROJECT_ROOT / "data"
        self.search_enabled: bool = os.getenv("SEARCH_ENABLED", "1") != "0"
        self.search_engine: str = os.getenv("SEARCH_ENGINE", "bing").lower()
        self.search_api_key: str = os.getenv("SEARCH_API_KEY", "").strip()

        # 图片理解（独立的视觉模型；不配置则识图功能关闭，回到"表情包"泛指）
        self.vision_base_url: str = os.getenv("VISION_BASE_URL", "").strip()
        self.vision_api_key: str = os.getenv("VISION_API_KEY", "").strip()
        self.vision_model: str = os.getenv("VISION_MODEL", "").strip()

        # 网友式多条消息之间的发送间隔（秒）
        self.send_interval: float = float(os.getenv("SEND_INTERVAL", "3.0"))

        # 主动发消息（久别后菟菚主动找你）
        self.proactive_check_minutes: float = float(os.getenv("PROACTIVE_CHECK_MINUTES", "15"))
        self.proactive_idle_hours: float = float(os.getenv("PROACTIVE_IDLE_HOURS", "4"))
        self.proactive_cooldown_hours: float = float(os.getenv("PROACTIVE_COOLDOWN_HOURS", "8"))


config = Config()
