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
