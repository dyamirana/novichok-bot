import hashlib
import re


def btn_id(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()[:10]


def extract_spoiler_from_caption(caption: str) -> tuple[str, bool]:
    if not caption:
        return "", False
    text = caption
    has = False
    markers = ["#spoiler", "[spoiler]", "(spoiler)", "#спойлер", "[спойлер]", "(спойлер)"]
    for m in markers:
        if m.lower() in text.lower():
            has = True
            text = re.sub(re.escape(m), "", text, flags=re.IGNORECASE)
    return text.strip(), has
