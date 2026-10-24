"""
Formatting and splitting helpers for the Assistant API.

Transforms generator output into formats:
- "markdown": clean markdown text
- "text": plain text without markdown or HTML markup
- "telegram_html": valid Telegram HTML (b, i, u, s, a, code, pre, blockquote, escaped & < >)

Splits text into chunks <= 4096 characters for Telegram, ensuring:
- Safe split on paragraph (\\n\\n), line (\\n), or word boundaries
- Never cuts inside an HTML tag or entity
- Every part has strictly balanced tags (reopens and closes tags across chunks)
"""
import html
import re
from dataclasses import asdict, dataclass
from typing import List, Optional, Tuple

from src.generation.validator import CitationItem

TELEGRAM_ALLOWED_TAGS = {"b", "i", "u", "s", "a", "code", "pre", "blockquote"}


@dataclass
class StructuredCitation:
    number: int
    canonical_id: str
    title: str
    law_number: str
    article: str
    article_title: str
    url: Optional[str]
    source_type: str
    status: str
    quote: str

    def to_dict(self) -> dict:
        return asdict(self)


def format_citations(citations: List[CitationItem]) -> List[StructuredCitation]:
    """Builds structured citations from CitationItem list."""
    out = []
    for c in citations or []:
        stype = getattr(c, "source_type", "lex") or "lex"
        # Curated editorial answers have no public Lex.uz URL
        pub_url = None if stype == "curated" else (getattr(c, "source_url", None) or None)
        out.append(
            StructuredCitation(
                number=getattr(c, "index", 1),
                canonical_id=getattr(c, "canonical_id", "") or "",
                title=getattr(c, "law_title", "") or "",
                law_number=getattr(c, "law_number", "") or "",
                article=getattr(c, "article_number", "") or "",
                article_title=getattr(c, "article_title", "") or "",
                url=pub_url,
                source_type=stype,
                status=getattr(c, "status", "active") or "active",
                quote=getattr(c, "quote_snippet", "") or "",
            )
        )
    return out


def telegram_sources_block(citations: List[StructuredCitation], language: str = "uz") -> str:
    """Numbered source list for telegram_html: the [n] markers in the answer point here (a chat has no other UI)."""
    lines = []
    for c in citations:
        title = c.title if len(c.title) <= 90 else c.title[:87].rstrip() + "…"
        label = f"{title} ({c.law_number})" if title and c.law_number else (title or c.law_number or c.canonical_id)
        if c.article:
            label = f"{label}, {c.article}"
        label = html.escape(label, quote=False)
        if c.url and c.url.startswith(("https://", "http://")):
            lines.append(f'[{c.number}] <a href="{html.escape(c.url, quote=True)}">{label}</a>')
        else:
            lines.append(f"[{c.number}] {label}")
    if not lines:
        return ""
    heading = {"ru": "📚 <b>Источники</b>", "en": "📚 <b>Sources</b>"}.get(language, "📚 <b>Manbalar</b>")
    return heading + "\n\n" + "\n\n".join(lines)


def to_plain_text(markdown_text: str) -> str:
    """Removes all markdown formatting and HTML tags for pure plain text."""
    if not markdown_text:
        return ""

    text = markdown_text

    # Code blocks: ```lang ... ``` -> ...
    text = re.sub(r"```[a-zA-Z0-9_\-]*\n?(.*?)```", r"\1", text, flags=re.DOTALL)
    # Inline code
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Links [label](url) -> label
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Images ![alt](url) -> ""
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"", text)
    # Horizontal rules
    text = re.sub(r"^\s*(?:---+|\*\*\*+|___+)\s*$", "", text, flags=re.MULTILINE)
    # Bold / italic
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    # Strikethrough
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    # Headings: # Heading -> Heading
    text = re.sub(r"^#{1,6}\s+(.+)$", r"\1", text, flags=re.MULTILINE)
    # Blockquotes: > Quote -> Quote
    text = re.sub(r"^>\s*(.+)$", r"\1", text, flags=re.MULTILINE)
    # List items: - item / * item -> • item
    text = re.sub(r"^(\s*)[*+-]\s+", r"\1• ", text, flags=re.MULTILINE)
    # Strip real HTML tags only (a "<" in legal text, e.g. "yoshi <18", must survive)
    text = re.sub(r"</?(?:b|i|u|s|a|code|pre|br|p|div|span|blockquote|strong|em|ul|ol|li|h[1-6])(?:\s[^>]*)?/?>",
                  "", text, flags=re.IGNORECASE)
    # Unescape HTML entities
    text = html.unescape(text)

    # Normalize multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_well_formed_telegram_html(text: str) -> bool:
    """Only Telegram tags, properly nested and closed (Telegram rejects the whole message otherwise)."""
    stack: List[str] = []
    for t_type, _, name in _tokenize_html(text):
        if t_type == "open_tag":
            if name not in TELEGRAM_ALLOWED_TAGS:
                return False
            stack.append(name)
        elif t_type == "close_tag":
            if not stack or stack[-1] != name:
                return False
            stack.pop()
    return not stack


def to_telegram_html(markdown_text: str) -> str:
    """Markdown -> Telegram HTML; falls back to escaped plain text when the markup would not nest cleanly."""
    if not markdown_text:
        return ""
    converted = _markdown_to_telegram_html(markdown_text)
    if is_well_formed_telegram_html(converted):
        return converted
    return html.escape(to_plain_text(markdown_text), quote=False)


def _decorate_section_heading(line: str) -> str:
    """Adds subtle visual icons to standalone bold section headings in Telegram HTML."""
    m = re.match(r"^<b>([^<]+)</b>(:?)$", line.strip())
    if not m:
        if line.strip().startswith("<b>Qisqa javob:") or line.strip().startswith("<b>Короткий ответ:"):
            return "⚖️ " + line.strip()
        return line
    heading_inner = m.group(1).strip()
    trail = m.group(2)
    # Skip if already starts with an emoji/symbol
    if heading_inner and not heading_inner[0].isalnum():
        return line
    low = heading_inner.lower()
    if any(k in low for k in ("nima qilish", "qadam", "murojaat", "tartib", "что делать", "порядок", "шаг", "what to do", "steps")):
        return f"📋 <b>{heading_inner}{trail}</b>"
    if any(k in low for k in ("yordam", "imtiyoz", "huquq", "shart", "toifa", "льгот", "помощ", "прав", "услов", "benefit", "right")):
        return f"📌 <b>{heading_inner}{trail}</b>"
    return line


def _markdown_to_telegram_html(markdown_text: str) -> str:
    """
    Converts markdown to Telegram-compatible HTML:
    - Escapes &, <, > in regular text
    - Removes raw horizontal rules (---)
    - Wraps disclaimer (*Eslatma:...*) in a clean <blockquote><i>ℹ️ ...</i></blockquote>
    - Headings -> bold lines (<b>Heading</b>) with contextual icons
    - List items -> spaced • Item and <b>1.</b> Item for clean mobile readability
    - Markdown bold -> <b>...</b>
    - Markdown italic -> <i>...</i>
    - Markdown underline / strike -> <u>...</u> / <s>...</s>
    - Markdown code -> <code>...</code>
    - Markdown pre -> <pre>...</pre>
    - Markdown quotes -> <blockquote>...</blockquote>
    - Markdown links -> <a href="...">...</a>
    """
    if not markdown_text:
        return ""

    text = markdown_text

    # 1. Protect code blocks (pre)
    code_blocks = []
    def _save_pre(m):
        code = m.group(1)
        # Escape entities inside code
        escaped_code = html.escape(code.strip("\n"), quote=False)
        idx = len(code_blocks)
        code_blocks.append(f"<pre>{escaped_code}</pre>")
        return f"@@PRE_BLOCK_{idx}@@"

    text = re.sub(r"```(?:[a-zA-Z0-9_\-]+)?\n?(.*?)```", _save_pre, text, flags=re.DOTALL)

    # 2. Protect inline code
    inline_codes = []
    def _save_code(m):
        code = m.group(1)
        escaped_code = html.escape(code, quote=False)
        idx = len(inline_codes)
        inline_codes.append(f"<code>{escaped_code}</code>")
        return f"@@INLINE_CODE_{idx}@@"

    text = re.sub(r"`([^`\n]+)`", _save_code, text)

    # 2b. Remove standalone markdown horizontal rules (---, ***, ___)
    text = re.sub(r"^\s*(?:---+|\*\*\*+|___+)\s*$", "", text, flags=re.MULTILINE)

    # 3. Escape HTML in the remaining text (&, <, >)
    text = html.escape(text, quote=False)

    # 4. Headings: `# Heading` -> `<b>Heading</b>`
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # 5. List items: `* item` or `- item` -> `• item`; numbered `1. item` -> `**1.** item`
    text = re.sub(r"^(\s*)[*+-]\s+", r"\1• ", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*)(\d+\.)\s+(?!\*)", r"\1**\2** ", text, flags=re.MULTILINE)

    # 6. Blockquotes: `> quote` -> `<blockquote>quote</blockquote>`
    # Handle single or multi-line blockquotes
    lines = text.split("\n")
    processed_lines = []
    in_quote = False
    quote_acc = []

    for line in lines:
        if line.startswith("&gt; ") or line == "&gt;":
            quote_text = line[5:] if line.startswith("&gt; ") else ""
            quote_acc.append(quote_text)
            in_quote = True
        else:
            if in_quote:
                processed_lines.append(f"<blockquote>{chr(10).join(quote_acc)}</blockquote>")
                quote_acc = []
                in_quote = False
            processed_lines.append(line)
    if in_quote:
        processed_lines.append(f"<blockquote>{chr(10).join(quote_acc)}</blockquote>")

    text = "\n".join(processed_lines)

    # 7. Links: [text](url) -> <a href="url">text</a>
    def _fmt_link(m):
        label = m.group(1)
        url = m.group(2).strip()
        # Clean url in case it was escaped
        url = html.unescape(url)
        # Ensure safe http/https protocol
        if url.startswith(("http://", "https://", "tg://")):
            safe_url = html.escape(url, quote=True)
            return f'<a href="{safe_url}">{label}</a>'
        return label

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _fmt_link, text)

    # 8. Bold: **bold** or __bold__
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__([^_]+)__", r"<b>\1</b>", text)

    # 9. Strikethrough: ~~strike~~
    text = re.sub(r"~~([^~]+)~~", r"<s>\1</s>", text)

    # 10. Italic: *italic* or _italic_
    text = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"<i>\1</i>", text)

    # 10b. Convert italicized disclaimer into a styled blockquote card
    text = re.sub(
        r"^<i>((?:Eslatma|Примечание|Disclaimer):[^\n]+)</i>$",
        r"<blockquote><i>ℹ️ \1</i></blockquote>",
        text,
        flags=re.MULTILINE,
    )

    # 10c. Decorate section headings and add breathing room between consecutive list/step items
    raw_out_lines = text.split("\n")
    spaced_lines: List[str] = []
    for idx, ln in enumerate(raw_out_lines):
        decorated = _decorate_section_heading(ln)
        if idx > 0:
            prev = spaced_lines[-1].strip() if spaced_lines else ""
            curr = decorated.strip()
            is_curr_list = curr.startswith("• ") or bool(re.match(r"^<b>\d+\.</b>\s", curr))
            is_prev_list = prev.startswith("• ") or bool(re.match(r"^<b>\d+\.</b>\s", prev))
            if is_curr_list and is_prev_list:
                spaced_lines.append("")
        spaced_lines.append(decorated)
    text = "\n".join(spaced_lines)

    # 11. Restore inline code and code blocks
    for idx, code_html in enumerate(inline_codes):
        text = text.replace(f"@@INLINE_CODE_{idx}@@", code_html)
    for idx, pre_html in enumerate(code_blocks):
        text = text.replace(f"@@PRE_BLOCK_{idx}@@", pre_html)

    # Clean redundant blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# HTML tag and entity parser for split_parts
_TAG_OR_ENTITY = re.compile(
    r"(?P<close_tag></(?P<close_name>[a-zA-Z0-9]+)>)|"
    r"(?P<open_tag><(?P<open_name>[a-zA-Z0-9]+)(?:\s+[^>]*)?>)|"
    r"(?P<entity>&(?:[a-zA-Z0-9]+|#[0-9]+|#x[0-9a-fA-F]+);)|"
    r"(?P<char>[\s\S])"
)


def _tokenize_html(text: str) -> List[Tuple[str, str, Optional[str]]]:
    """
    Tokenizes text into a list of tuples: (token_type, token_str, tag_name).
    Types: 'open_tag', 'close_tag', 'entity', 'char'.
    """
    tokens = []
    for m in _TAG_OR_ENTITY.finditer(text):
        if m.group("close_tag"):
            tokens.append(("close_tag", m.group("close_tag"), m.group("close_name").lower()))
        elif m.group("open_tag"):
            tokens.append(("open_tag", m.group("open_tag"), m.group("open_name").lower()))
        elif m.group("entity"):
            tokens.append(("entity", m.group("entity"), None))
        else:
            tokens.append(("char", m.group("char"), None))
    return tokens


def split_parts(text: str, limit: int = 4096) -> List[str]:
    """
    Splits text into chunks <= limit (default 4096):
    - Splits preferentially on paragraph (\\n\\n), then line (\\n), then word boundaries (' ')
    - Never cuts inside an HTML tag or HTML entity
    - Every part has balanced tags (close unclosed tags at chunk end, reopen at chunk start)
    """
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    tokens = _tokenize_html(text)
    parts = []

    idx = 0
    num_tokens = len(tokens)
    open_tags: List[Tuple[str, str]] = []  # List of (tag_name, full_open_tag)

    while idx < num_tokens:
        chunk_tokens = []
        chunk_open_tags = list(open_tags)

        # Prefix for reopening previously open tags
        reopen_prefix = "".join(ot for _, ot in open_tags)
        curr_len = len(reopen_prefix)

        # Keep track of split candidates: (token_index_in_tokens, open_tags_state_at_cut)
        best_para_cut: Optional[Tuple[int, List[Tuple[str, str]]]] = None
        best_line_cut: Optional[Tuple[int, List[Tuple[str, str]]]] = None
        best_word_cut: Optional[Tuple[int, List[Tuple[str, str]]]] = None
        last_safe_cut: Optional[Tuple[int, List[Tuple[str, str]]]] = None

        scan_idx = idx
        while scan_idx < num_tokens:
            t_type, t_str, t_name = tokens[scan_idx]

            # Calculate closing tags string if we split right after this token
            temp_open = list(chunk_open_tags)
            if t_type == "open_tag" and t_name in TELEGRAM_ALLOWED_TAGS:
                temp_open.append((t_name, t_str))
            elif t_type == "close_tag" and t_name in TELEGRAM_ALLOWED_TAGS:
                # Pop from end of temp_open matching tag name
                for i in range(len(temp_open) - 1, -1, -1):
                    if temp_open[i][0] == t_name:
                        temp_open.pop(i)
                        break

            closing_str = "".join(f"</{t}>" for t, _ in reversed(temp_open))
            closing_len = len(closing_str)

            if curr_len + len(t_str) + closing_len > limit:
                # Can't fit this token with its closing tags
                break

            # Fits!
            curr_len += len(t_str)
            chunk_tokens.append(t_str)
            chunk_open_tags = temp_open
            scan_idx += 1

            # Check boundary types for clean splitting
            last_safe_cut = (scan_idx, list(chunk_open_tags))

            if t_type == "char":
                if t_str == "\n":
                    # Check if preceded by \n for paragraph
                    if len(chunk_tokens) >= 2 and chunk_tokens[-2] == "\n":
                        best_para_cut = (scan_idx, list(chunk_open_tags))
                    else:
                        best_line_cut = (scan_idx, list(chunk_open_tags))
                elif t_str in (" ", "\t"):
                    best_word_cut = (scan_idx, list(chunk_open_tags))

        if scan_idx >= num_tokens:
            # Reached the end of text!
            part_body = reopen_prefix + "".join(chunk_tokens)
            parts.append(part_body)
            break

        # Choose the best cut point
        chosen_cut = None
        if best_para_cut:
            chosen_cut = best_para_cut
        elif best_line_cut:
            chosen_cut = best_line_cut
        elif best_word_cut:
            chosen_cut = best_word_cut
        elif last_safe_cut:
            chosen_cut = last_safe_cut
        else:
            # Even one token doesn't fit! Force take at least one token to avoid infinite loop
            scan_idx = idx + 1
            chosen_cut = (scan_idx, list(chunk_open_tags))

        cut_idx, cut_tags = chosen_cut
        tokens_for_part = [tokens[i][1] for i in range(idx, cut_idx)]
        closing_tags_str = "".join(f"</{t}>" for t, _ in reversed(cut_tags))

        part_content = reopen_prefix + "".join(tokens_for_part) + closing_tags_str
        parts.append(part_content)

        # Update open_tags for the next part
        open_tags = cut_tags
        idx = cut_idx

    return [p for p in parts if p.strip()]
