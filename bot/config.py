import os
import sys
from collections import defaultdict, deque
from pathlib import Path

try:
    from loguru import logger
    _LOGURU = True
except Exception:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("bot")
    _LOGURU = False

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
_GROUP_IDS_RAW = os.getenv("GROUP_IDS", "").strip()
_GROUP_ID_SINGLE = os.getenv("GROUP_ID", "0").strip()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DB_PATH = Path(os.getenv("DB_PATH", "data/bot.db"))
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

chat_history: dict[int, deque[str]] = defaultdict(lambda: deque(maxlen=50))

def setup_logging():
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    if '_LOGURU' in globals() and _LOGURU:
        logger.remove()
        logger.add(
            sys.stdout,
            level=level,
            backtrace=False,
            diagnose=False,
            enqueue=True,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        )

def _parse_group_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    if not raw:
        return ids
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            continue
    return ids

ALLOWED_CHAT_IDS: set[int] = _parse_group_ids(_GROUP_IDS_RAW)
if not ALLOWED_CHAT_IDS and _GROUP_ID_SINGLE and _GROUP_ID_SINGLE != "0":
    try:
        ALLOWED_CHAT_IDS = {int(_GROUP_ID_SINGLE)}
    except ValueError:
        ALLOWED_CHAT_IDS = set()

def is_group_allowed(chat_id: int) -> bool:
    return chat_id in ALLOWED_CHAT_IDS
