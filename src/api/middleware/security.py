import re
import logging
from fastapi import Request, HTTPException

logger = logging.getLogger(__name__)

# Prompt injection patterns
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"forget\s+(all\s+)?(previous|prior)\s+instructions",
    r"system\s*prompt\s*override",
    r"you\s+are\s+now\s+dan",
    r"bypass\s+rules",
    r"jailbreak",
    r"you\s+must\s+act\s+as\s+unfiltered",
]

INJECTION_REGEX = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


def sanitize_user_input(text: str) -> str:
    """Detects and neutralizes malicious prompt injection attempts."""
    if INJECTION_REGEX.search(text):
        logger.warning(f"Potential prompt injection detected: {text[:100]}")
        raise HTTPException(
            status_code=400,
            detail="Xavfsizlik qoidalariga zid so'rov aniqlandi (Potentially unsafe prompt pattern detected)."
        )
    # Strip dangerous non-printable control characters
    cleaned = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")
    return cleaned.strip()
