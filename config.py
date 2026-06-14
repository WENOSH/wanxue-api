""" WanXue API Configuration """

import os
from pathlib import Path

# ── 自动加载 .env（无需依赖外部 dotenv 工具） ─────
try:
    from dotenv import load_dotenv
    _ENV_PATH = Path(__file__).parent / ".env"
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH, override=False)
except ImportError:
    pass

# ── LLM ──────────────────────────────────────────
LLM_PROVIDER = os.getenv("WANXUE_LLM_PROVIDER", "deepseek")
LLM_API_KEY = os.getenv("WANXUE_API_KEY", "")
LLM_MODEL = os.getenv("WANXUE_LLM_MODEL", "deepseek-chat")
LLM_BASE_URL = os.getenv("WANXUE_LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_MAX_TOKENS = int(os.getenv("WANXUE_LLM_MAX_TOKENS", "8192"))
LLM_TEMPERATURE = float(os.getenv("WANXUE_LLM_TEMPERATURE", "0.7"))

# ── Output ───────────────────────────────────────
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# ── Server ───────────────────────────────────────
HOST = os.getenv("WANXUE_HOST", "0.0.0.0")
PORT = int(os.getenv("WANXUE_PORT", "8000"))
LOG_LEVEL = os.getenv("WANXUE_LOG_LEVEL", "info")

# ── Course Limits ────────────────────────────────
MAX_CHAPTERS = int(os.getenv("WANXUE_MAX_CHAPTERS", "5"))
MAX_CARDS_PER_CHAPTER = int(os.getenv("WANXUE_MAX_CARDS_PER_CHAPTER", "8"))

# ── Difficulty Levels ────────────────────────────
# 难度等级及其对应的章节数、每章卡片数
DIFFICULTY_LEVELS = {
    "1-入门":  {"chapters": 4, "cards": 5, "label": "入门轻松", "desc": "轻松趣味，适合零基础/小孩"},
    "2-基础":  {"chapters": 5, "cards": 6, "label": "基础标准", "desc": "系统学习，适合初学者"},
    "3-标准":  {"chapters": 6, "cards": 7, "label": "标准全面", "desc": "全面深入，适合有基础"},
    "4-进阶":  {"chapters": 7, "cards": 7, "label": "进阶专业", "desc": "专业深度，适合深入研究"},
    "5-挑战":  {"chapters": 8, "cards": 8, "label": "挑战高阶", "desc": "高难度，适合专家级"},
}
DEFAULT_DIFFICULTY = "3-标准"

def get_difficulty_config(difficulty: str = None) -> dict:
    """获取难度等级配置，返回 {label, chapters, cards, desc}"""
    if not difficulty or difficulty not in DIFFICULTY_LEVELS:
        difficulty = DEFAULT_DIFFICULTY
    return {"key": difficulty, **DIFFICULTY_LEVELS[difficulty]}
