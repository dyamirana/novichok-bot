import json
import time
import aiosqlite

from .config import DB_PATH, ADMIN_ID


db: aiosqlite.Connection | None = None


async def init_db() -> aiosqlite.Connection:
    global db
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS config
        (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS buttons
        (
            label    TEXT PRIMARY KEY,
            response TEXT
        );
        CREATE TABLE IF NOT EXISTS allowed_users
        (
            user_id INTEGER PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS banned_users
        (
            user_id INTEGER PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS rate_limit
        (
            user_id INTEGER PRIMARY KEY,
            last_ts INTEGER
        );
        """
    )
    await db.commit()
    return db


async def get_config(key: str, default=None):
    async with db.execute("SELECT value FROM config WHERE key=?", (key,)) as cur:
        row = await cur.fetchone()
    return row[0] if row else default


async def set_config(key: str, value: str) -> None:
    await db.execute("REPLACE INTO config(key,value) VALUES(?,?)", (key, value))
    await db.commit()


async def get_greeting() -> dict:
    data = await get_config("greeting")
    if data:
        return json.loads(data)
    return {"type": "text", "text": "Привет, {user}!"}


async def set_greeting(greet: dict) -> None:
    await set_config("greeting", json.dumps(greet))


async def get_question() -> str:
    return await get_config("question", "")


async def set_question(question: str) -> None:
    await set_config("question", question)


async def get_buttons() -> dict:
    buttons: dict[str, dict] = {}
    async with db.execute("SELECT label,response FROM buttons") as cur:
        async for label, response in cur:
            try:
                payload = json.loads(response)
                if isinstance(payload, dict) and "type" in payload:
                    buttons[label] = payload
                else:
                    buttons[label] = {"type": "text", "text": str(payload)}
            except Exception:
                buttons[label] = {"type": "text", "text": response}
    return buttons


async def add_button(label: str, response: str) -> None:
    await db.execute("REPLACE INTO buttons(label,response) VALUES(?,?)", (label, response))
    await db.commit()


async def remove_button(label: str) -> None:
    await db.execute("DELETE FROM buttons WHERE label=?", (label,))
    await db.commit()


async def get_allowed_users() -> list:
    users = []
    async with db.execute("SELECT user_id FROM allowed_users") as cur:
        async for (uid,) in cur:
            users.append(uid)
    return users


async def add_allowed_user(uid: int) -> None:
    await db.execute("INSERT OR IGNORE INTO allowed_users(user_id) VALUES(?)", (uid,))
    await db.commit()


async def remove_allowed_user(uid: int) -> None:
    await db.execute("DELETE FROM allowed_users WHERE user_id=?", (uid,))
    await db.commit()


async def is_allowed(uid: int) -> bool:
    if uid == ADMIN_ID:
        return True
    async with db.execute("SELECT 1 FROM allowed_users WHERE user_id=?", (uid,)) as cur:
        return await cur.fetchone() is not None


async def add_banned_user(uid: int) -> None:
    if db is None:
        return
    await db.execute("INSERT OR IGNORE INTO banned_users(user_id) VALUES(?)", (uid,))
    await db.commit()


async def is_banned(uid: int) -> bool:
    if db is None:
        return False
    async with db.execute("SELECT 1 FROM banned_users WHERE user_id=?", (uid,)) as cur:
        return await cur.fetchone() is not None


async def check_rate(uid: int) -> tuple[bool, int]:
    if uid == ADMIN_ID or await is_allowed(uid):
        return True, 0
    now = int(time.time())
    async with db.execute("SELECT last_ts FROM rate_limit WHERE user_id=?", (uid,)) as cur:
        row = await cur.fetchone()
    if row and now - row[0] < 60:
        return False, 60 - (now - row[0])
    await db.execute("REPLACE INTO rate_limit(user_id,last_ts) VALUES(?,?)", (uid, now))
    await db.commit()
    return True, 0
