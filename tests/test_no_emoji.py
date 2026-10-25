"""Answers, the admin API and the web pages carry no emoji (owner's rule, 2026-10-25)."""
import re
from pathlib import Path

EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF️]")
ROOT = Path(__file__).resolve().parents[1]


def test_web_pages_and_answer_code_have_no_emoji():
    files = [p for p in (ROOT / "src").rglob("*") if p.suffix in (".py", ".js", ".html", ".css") and "scratch" not in p.parts]
    offenders = [str(p.relative_to(ROOT)) for p in files if EMOJI.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert offenders == []
