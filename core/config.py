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
        # 收到消息后到发第一条回复的"酝酿"延迟（秒）：
        # 模拟真人看到消息、想一下、开始打字的节奏，避免秒回显得像机器人
        self.think_delay: float = float(os.getenv("THINK_DELAY", "2.0"))
        # 消息去抖窗口（秒）：用户连发消息时，此时间内到达的都合并成一条整体处理。
        # 菟菚会等用户把话说完整（观察对方会不会继续打第二句/第三句），再精简成一句回应。
        self.debounce_seconds: float = float(os.getenv("DEBOUNCE_SECONDS", "4.0"))
        # 回复延迟的随机抖动比例（0~1）：真人的反应时间不是固定的，加随机量避免规律性，
        # 既是真人感，也能降低被风控识别为"固定节奏机器人"的概率。
        self.delay_jitter: float = float(os.getenv("DELAY_JITTER", "0.4"))

        # 主动发消息（久别后菟菚主动找你）
        self.proactive_check_minutes: float = float(os.getenv("PROACTIVE_CHECK_MINUTES", "15"))
        self.proactive_idle_hours: float = float(os.getenv("PROACTIVE_IDLE_HOURS", "4"))
        self.proactive_cooldown_hours: float = float(os.getenv("PROACTIVE_COOLDOWN_HOURS", "8"))
        # 允许被主动发消息的 QQ 号（逗号分隔多个；留空则对最后说话的人发）
        raw = os.getenv("PROACTIVE_USER_ID", "").strip()
        self.proactive_user_ids: list[str] = [x.strip() for x in raw.split(",") if x.strip()]

        # 记忆语义检索：用户疑似回忆（上次/之前/还记得…）时，先用 LLM 把问题
        # 扩展成多个检索词再查长期记忆，提升召回；关闭则退回 v1 关键词检索
        self.memory_semantic: bool = os.getenv("MEMORY_SEMANTIC", "1") != "0"

        # 图像生成（SiliconFlow 文生图；不配置则生图功能关闭）
        self.image_base_url: str = os.getenv("IMAGE_BASE_URL", "https://api.siliconflow.cn/v1").strip()
        self.image_api_key: str = os.getenv("IMAGE_API_KEY", "").strip()
        self.image_model: str = os.getenv("IMAGE_MODEL", "Kwai-Kolors/Kolors").strip()

        # 心情系统：天气城市（留空则按时间段兜底基线，不查天气）
        self.mood_city: str = os.getenv("MOOD_CITY", "").strip()


config = Config()
