"""
src/my_news_generator.py  –  Generate my-news markdown via DeepSeek API.
"""
from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
from html import escape
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_API_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_TIMEOUT,
    MY_NEWS_PRUNE_INVALID_SOURCE_ITEMS,
    MY_NEWS_MAX_TOKENS,
    REPORT_WINDOW_HOUR,
    REPORT_WINDOW_MODE,
    REPORT_WINDOW_TZ_OFFSET,
)
from src.skills import get_my_news_prompt


_BJT = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)
_SECTION_HEADER_RE = re.compile(r"<h3>-\s*(\d{2})\s+.+\s*-</h3>")
_MARKDOWN_SECTION_RE = re.compile(r"^##\s*(\d{2})\b")
_MARKDOWN_ITEM_RE = re.compile(r"^###\s*\d+\.\s+(.+)$")
_SCORE_PATTERN = re.compile(
    r"\[\[\s*(?:(\d+(?:\.\d+)?)\s*/\s*10|(\d+(?:\.\d+)?))\s*]]"
)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^]]*)]\(([^)\s]+)\)")
_PLAIN_SECTION_TITLE_RE = re.compile(r"^-\s*(\d{2})\s+(.+?)\s*-$")
_GENERATION_CHATTER_RE = re.compile(
    r"^(我将|让我|首先|然后|开始执行|立即开始工作|下面开始|接下来|步骤|\d+\.|\d+、)"
)
_INTRO_SECTION_LINE_RE = re.compile(r"^[\-*\s]*?(\d{2})\s+[^：:]+[：:]\s*(.+)$")
_PARAGRAPH_LABEL_RE = re.compile(r"^[\[【]正文(?:段落)?[\]】]\s*[：:]\s*")
_WRAPPED_PARAGRAPH_LABEL_RE = re.compile(
    r"^[\[【]\s*正文(?:段落)?\s*[：:]\s*(.*?)\s*[\]】]\s*$"
)
_CORE_PAPER_ALLOWED_DOMAINS = {
    "arxiv.org",
    "nature.com",
    "science.org",
    "pnas.org",
    "ieeexplore.ieee.org",
    "dl.acm.org",
    "scholar.google.com",
    "semanticscholar.org",
    "biorxiv.org",
    "aclanthology.org",
}
_CORE_PAPER_EMPTY_TEXT = "今日暂无符合标准的资讯（未提供可信学术来源URL）。"


def _get_templates_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "templates"
    return Path(__file__).parent.parent / "templates"


def _is_anthropic_style_api(url: str) -> bool:
    normalized = (url or "").strip().lower()
    return "/api/anthropic" in normalized or normalized.endswith("/v1/messages")


def _resolve_chat_endpoint(url: str) -> str:
    endpoint = (url or "").strip().rstrip("/")
    if _is_anthropic_style_api(endpoint) and not endpoint.endswith("/v1/messages"):
        return f"{endpoint}/v1/messages"
    return endpoint


def _resolve_max_tokens(endpoint: str) -> int:
    """Resolve max output tokens with optional env override and provider-aware defaults."""
    if MY_NEWS_MAX_TOKENS > 0:
        return MY_NEWS_MAX_TOKENS

    normalized = (endpoint or "").lower()
    if "open.bigmodel.cn" in normalized and _is_anthropic_style_api(normalized):
        # GLM Anthropic endpoint supports larger output limits.
        return 131072
    if _is_anthropic_style_api(normalized):
        return 32768
    return 8192


def _extract_text_from_anthropic_response(data: dict) -> tuple[str, str | None]:
    blocks = data.get("content") or []
    text_parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append((block.get("text") or "").strip())
    return "\n".join([p for p in text_parts if p]).strip(), data.get("stop_reason")


def _extract_text_from_openai_response(data: dict) -> tuple[str, str | None]:
    choice = data.get("choices", [{}])[0]
    return (choice.get("message", {}).get("content", "") or "").strip(), choice.get("finish_reason")


def _split_system_and_dialog_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    system_text = ""
    dialog: list[dict] = []
    for msg in messages:
        role = (msg.get("role") or "").strip()
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        if role == "system":
            system_text = f"{system_text}\n\n{content}".strip() if system_text else content
            continue
        if role in ("user", "assistant"):
            dialog.append({"role": role, "content": content})
    if not dialog:
        dialog.append({"role": "user", "content": "请直接输出日报Markdown正文。"})
    return system_text, dialog


def _call_llm_api(messages: list[dict]) -> tuple[str, str | None]:
    endpoint = _resolve_chat_endpoint(DEEPSEEK_API_URL)
    max_tokens = _resolve_max_tokens(endpoint)
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    if _is_anthropic_style_api(endpoint):
        headers["anthropic-version"] = "2023-06-01"
        system_text, dialog_messages = _split_system_and_dialog_messages(messages)
        payload = {
            "model": DEEPSEEK_MODEL,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "messages": dialog_messages,
        }
        if system_text:
            payload["system"] = system_text
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=DEEPSEEK_TIMEOUT)
        resp.raise_for_status()
        return _extract_text_from_anthropic_response(resp.json())

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    resp = requests.post(endpoint, headers=headers, json=payload, timeout=DEEPSEEK_TIMEOUT)
    resp.raise_for_status()
    return _extract_text_from_openai_response(resp.json())


def _generate_with_continuation(messages: list[dict], max_rounds: int = 3) -> tuple[str, str | None]:
    """Generate report text and automatically request continuation if truncated."""
    merged_parts: list[str] = []
    working_messages = list(messages)
    finish_reason: str | None = None

    for idx in range(max_rounds):
        chunk, finish_reason = _call_llm_api(working_messages)
        chunk = (chunk or "").strip()
        if chunk:
            merged_parts.append(chunk)

        if finish_reason not in ("length", "max_tokens"):
            break

        logger.warning(
            "Model output truncated (%s), requesting continuation %d/%d.",
            finish_reason,
            idx + 1,
            max_rounds,
        )
        working_messages.extend(
            [
                {"role": "assistant", "content": chunk or "(empty)"},
                {
                    "role": "user",
                    "content": (
                        "你的输出被截断了。请从上一次最后一句后继续输出剩余日报内容，"
                        "不要重复前文，不要添加任何过程说明。"
                    ),
                },
            ]
        )

    return "\n".join([p for p in merged_parts if p]).strip(), finish_reason


_env = Environment(
    loader=FileSystemLoader(str(_get_templates_dir())),
    autoescape=select_autoescape(["html"]),
)


@dataclass
class MyNewsGenerationContext:
    now_utc: datetime
    bjt_now: datetime
    messages: list[dict]
    allowed_urls: set[str]


def _get_image_extension(image_url: str, content_type: str) -> str:
    path_ext = Path(urlparse(image_url).path).suffix.lower().lstrip(".")
    if path_ext in {"jpg", "jpeg", "png", "webp", "gif"}:
        return path_ext
    ctype = (content_type or "").lower()
    if "png" in ctype:
        return "png"
    if "webp" in ctype:
        return "webp"
    if "gif" in ctype:
        return "gif"
    if "jpeg" in ctype or "jpg" in ctype:
        return "jpg"
    return "jpg"


def _extract_url_from_related_link_line(text: str) -> str | None:
    markdown_url = re.search(r"\((https?://[^)\s]+)\)", text)
    if markdown_url:
        return markdown_url.group(1)
    plain_url = re.search(r"(https?://[^\s]+)", text)
    if plain_url:
        return plain_url.group(1).rstrip(").,")
    return None


def _normalize_url_for_dedupe(url: str) -> str:
    """Normalize source URLs so the same article maps to one dedupe key."""
    parsed = urlparse((url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return (url or "").strip()

    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if not host:
        return (url or "").strip()

    port = parsed.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"

    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")

    tracking_exact = {
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "igshid",
        "mc_cid",
        "mc_eid",
    }
    filtered_query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in tracking_exact
    ]
    query = urlencode(sorted(filtered_query), doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def _is_source_line(text: str) -> bool:
    stripped = text.strip()
    return (
        stripped.startswith("**相关链接：**")
        or stripped.startswith("**来源：**")
        or stripped.startswith("来源：")
    )


def _is_item_title_line(stripped: str) -> bool:
    return (
        stripped.startswith("**")
        and stripped.endswith("**")
        and not stripped.startswith("**相关链接：**")
    )


def _extract_section_code(line: str) -> str | None:
    html_match = _SECTION_HEADER_RE.search(line)
    if html_match:
        return html_match.group(1)

    md_match = _MARKDOWN_SECTION_RE.match(line.strip())
    if md_match:
        return md_match.group(1)
    return None


def _extract_item_title(line: str) -> str | None:
    stripped = line.strip()
    if _is_item_title_line(stripped):
        return stripped.strip("*").strip()

    md_match = _MARKDOWN_ITEM_RE.match(stripped)
    if md_match:
        return md_match.group(1).strip()
    return None


def _strip_model_preface(markdown: str) -> str:
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("# "):
            return "\n".join(lines[i:]).strip()
    return markdown.strip()


def _normalize_report_title_date(markdown: str, bjt_now: datetime) -> str:
    lines = markdown.splitlines()
    expected_title = (
        f"# {bjt_now.year}年{bjt_now.month}月{bjt_now.day}日 TBK日报：看见世界、发现自己"
    )
    for i, line in enumerate(lines):
        if line.lstrip().startswith("# ") and "TBK日报" in line:
            lines[i] = expected_title
            return "\n".join(lines)

    return f"{expected_title}\n\n{markdown.strip()}"


def _strip_generation_chatter(markdown: str) -> str:
    """Drop model process narration before the first actual report section."""
    lines = markdown.splitlines()
    if not lines:
        return markdown

    title_idx = -1
    for i, line in enumerate(lines):
        if line.lstrip().startswith("# "):
            title_idx = i
            break
    if title_idx == -1:
        return markdown

    # Strict rule: if content right after title does not start from 导读,
    # strip everything until the first "- 导读 -" marker.
    first_non_empty_idx = -1
    for i in range(title_idx + 1, len(lines)):
        if lines[i].strip():
            first_non_empty_idx = i
            break

    if first_non_empty_idx != -1 and "- 导读 -" not in lines[first_non_empty_idx]:
        intro_idx = -1
        for i in range(title_idx + 1, len(lines)):
            if "- 导读 -" in lines[i]:
                intro_idx = i
                break

        if intro_idx != -1:
            keep_from = intro_idx
            if intro_idx > title_idx + 1 and lines[intro_idx - 1].strip().startswith("<div"):
                keep_from = intro_idx - 1
            return "\n".join(lines[: title_idx + 1] + [""] + lines[keep_from:]).strip()

    out = lines[: title_idx + 1]
    body_started = False

    for line in lines[title_idx + 1 :]:
        stripped = line.strip()
        if body_started:
            out.append(line)
            continue

        # Real report body starts at导读/章节/分隔线等结构行。
        is_body_marker = (
            stripped.startswith("<div")
            or stripped.startswith("</div>")
            or stripped.startswith("<h3>")
            or stripped.startswith("<span ")
            or stripped == "---"
            or _extract_section_code(stripped) is not None
        )
        if is_body_marker:
            body_started = True
            out.append(line)
            continue

        if not stripped:
            out.append(line)
            continue

        if _GENERATION_CHATTER_RE.match(stripped):
            continue

        # Keep non-chatter fallback text to avoid over-filtering unknown formats.
        out.append(line)

    return "\n".join(out).strip()


def _parse_item_published_datetime(item: dict) -> datetime | None:
    published_at = (item.get("published_at") or "").strip()
    if published_at:
        try:
            dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    published = (item.get("published") or "").strip()
    if not published:
        return None
    try:
        day = datetime.fromisoformat(published)
        return day.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _get_report_window(now_utc: datetime) -> tuple[datetime, datetime]:
    normalized_mode = (REPORT_WINDOW_MODE or "anchored").strip().lower()
    if normalized_mode == "rolling":
        return now_utc - timedelta(days=1), now_utc

    tz = timezone(timedelta(hours=REPORT_WINDOW_TZ_OFFSET))
    local_now = now_utc.astimezone(tz)
    end_local = local_now.replace(hour=REPORT_WINDOW_HOUR, minute=0, second=0, microsecond=0)
    if local_now < end_local:
        end_local -= timedelta(days=1)
    start_local = end_local - timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _filter_items_for_window(items: list[dict], start_utc: datetime, end_utc: datetime) -> list[dict]:
    filtered: list[dict] = []
    for item in items:
        published_dt = _parse_item_published_datetime(item)
        if published_dt is not None and start_utc <= published_dt < end_utc:
            filtered.append(item)
    return filtered


def _score_to_star_text(score: float) -> str:
    clamped = min(10.0, max(0.0, score))
    half_units = int(round(clamped))
    full_stars = half_units // 2
    has_half = (half_units % 2) == 1
    empty_stars = 5 - full_stars - (1 if has_half else 0)
    return f"[{('★' * full_stars)}{('⯨' if has_half else '')}{('☆' * empty_stars)}]"


def _convert_scores_to_stars(markdown: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        number = match.group(1) or match.group(2)
        try:
            return _score_to_star_text(float(number))
        except Exception:
            return match.group(0)

    return _SCORE_PATTERN.sub(_replace, markdown)


def _is_url_reachable(url: str) -> bool | None:
    try:
        head = requests.head(url, allow_redirects=True, timeout=8)
        if head.status_code < 400:
            return True
        if head.status_code in (401, 403, 429):
            return True
        if head.status_code == 405:
            get_resp = requests.get(url, allow_redirects=True, timeout=8, stream=True)
            return get_resp.status_code < 400 or get_resp.status_code in (401, 403, 429)
        if head.status_code in (404, 410):
            return False
        if 500 <= head.status_code <= 599:
            return None
        return False
    except Exception:
        return None


def _sanitize_related_links(markdown: str, allowed_urls: set[str] | None = None) -> str:
    lines = markdown.splitlines()
    checked: dict[str, bool | None] = {}
    rewritten: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not _is_source_line(stripped):
            rewritten.append(line)
            continue

        url = _extract_url_from_related_link_line(stripped)
        if not url:
            rewritten.append("**相关链接：** 链接缺失（请人工补充）")
            continue

        if url not in checked:
            checked[url] = _is_url_reachable(url)

        if allowed_urls is not None and url not in allowed_urls:
            logger.warning("Source link not in trusted list, keep original URL: %s", url)

        status = checked[url]
        if status is False:
            logger.warning("Source link seems unreachable, keep original URL: %s", url)

        # Keep markdown and email style consistent.
        rewritten.append(f"**相关链接：** [阅读原文 ->]({url})")

    return "\n".join(rewritten)


def _strip_paragraph_labels(markdown: str) -> str:
    lines = markdown.splitlines()
    cleaned: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        wrapped_match = _WRAPPED_PARAGRAPH_LABEL_RE.match(stripped)
        if wrapped_match:
            cleaned.append(indent + wrapped_match.group(1).strip())
            continue
        cleaned.append(indent + _PARAGRAPH_LABEL_RE.sub("", stripped))
    return "\n".join(cleaned)


def _item_has_valid_source_line(item_lines: list[str]) -> bool:
    for line in item_lines:
        stripped = line.strip()
        if not _is_source_line(stripped):
            continue
        url = _extract_url_from_related_link_line(stripped)
        if url and url.startswith(("http://", "https://")):
            return True
    return False


def _extract_item_source_url(item_lines: list[str]) -> str | None:
    for line in item_lines:
        stripped = line.strip()
        if not _is_source_line(stripped):
            continue
        url = _extract_url_from_related_link_line(stripped)
        if url:
            return url
    return None


def _is_allowed_core_paper_domain(url: str) -> bool:
    host = (urlparse((url or "").strip()).hostname or "").lower().rstrip(".")
    if not host:
        return False
    return any(host == d or host.endswith(f".{d}") for d in _CORE_PAPER_ALLOWED_DOMAINS)


def _enforce_core_paper_source_domains(markdown: str) -> str:
    """Keep section 03 items only when source URL host matches academic whitelist."""
    lines = markdown.splitlines()
    out: list[str] = []
    removed = 0
    i = 0
    current_section: str | None = None

    while i < len(lines):
        line = lines[i]
        section = _extract_section_code(line)
        if section:
            current_section = section

        title = _extract_item_title(line)
        if not title:
            out.append(line)
            i += 1
            continue

        block: list[str] = [line]
        i += 1
        while i < len(lines):
            next_line = lines[i]
            if _extract_section_code(next_line) or _extract_item_title(next_line):
                break
            block.append(next_line)
            i += 1

        if current_section != "03":
            out.extend(block)
            continue

        source_url = _extract_item_source_url(block)
        if source_url and _is_allowed_core_paper_domain(source_url):
            out.extend(block)
            continue

        removed += 1
        logger.warning(
            "Removed non-academic core paper item: %s | source=%s",
            title,
            source_url or "(missing)",
        )

    if removed:
        logger.warning("Removed %d core paper item(s) by source domain guard.", removed)

    return "\n".join(out)


def _ensure_core_paper_fallback_text(markdown: str) -> str:
    """Ensure section 03 has a fallback sentence after strict source-domain filtering."""
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        section = _extract_section_code(line)
        if section != "03":
            out.append(line)
            i += 1
            continue

        block: list[str] = [line]
        i += 1
        while i < len(lines):
            next_line = lines[i]
            if _extract_section_code(next_line):
                break
            block.append(next_line)
            i += 1

        if not _section_has_content(block):
            if block and block[-1].strip():
                block.append("")
            block.append(_CORE_PAPER_EMPTY_TEXT)

        out.extend(block)

    return "\n".join(out)


def _dedupe_items_by_source_url(markdown: str) -> str:
    """Ensure each source URL appears once, preferring better section placement."""
    lines = markdown.splitlines()
    intro_fallbacks = _extract_intro_section_fallbacks(markdown)
    parsed_blocks: list[dict] = []
    url_groups: dict[str, list[dict]] = {}
    raw_section_counts: dict[str, int] = {}
    i = 0
    item_id = 0
    current_section: str | None = None

    while i < len(lines):
        line = lines[i]
        section = _extract_section_code(line)
        if section:
            current_section = section

        title = _extract_item_title(line)
        if not title:
            parsed_blocks.append({"type": "line", "line": line})
            i += 1
            continue

        block: list[str] = [line]
        i += 1
        while i < len(lines):
            next_line = lines[i]
            if _extract_section_code(next_line) or _extract_item_title(next_line):
                break
            block.append(next_line)
            i += 1

        source_url = _extract_item_source_url(block)
        normalized_url = _normalize_url_for_dedupe(source_url) if source_url else None
        section_code = current_section or "??"
        raw_section_counts[section_code] = raw_section_counts.get(section_code, 0) + 1
        item_entry = {
            "type": "item",
            "id": item_id,
            "section": current_section,
            "title": title,
            "block": block,
            "source_url": source_url,
            "normalized_url": normalized_url,
            "plain_text": re.sub(r"<[^>]+>", " ", " ".join(block)),
        }
        item_id += 1
        parsed_blocks.append(item_entry)
        if normalized_url:
            url_groups.setdefault(normalized_url, []).append(item_entry)

    def _tokenize(text: str) -> set[str]:
        return set(re.findall(r"[0-9A-Za-z\u4e00-\u9fff]{2,}", text.lower()))

    def _fit_score(candidate: dict) -> int:
        section_code = candidate.get("section") or ""
        summary = intro_fallbacks.get(section_code, "")
        if not summary:
            return 0
        summary_tokens = _tokenize(summary)
        if not summary_tokens:
            return 0
        item_tokens = _tokenize(f"{candidate.get('title', '')} {candidate.get('plain_text', '')}")
        return len(summary_tokens & item_tokens)

    def _section_priority(section_code: str | None) -> int:
        ordered = {
            "01": 7,
            "02": 6,
            "03": 5,
            "04": 4,
            "05": 3,
            "06": 2,
            "07": 1,
        }
        return ordered.get(section_code or "", 0)

    keep_item_ids: set[int] = set()
    kept_section_counts: dict[str, int] = {}

    # Items without source URL cannot be grouped; keep them as-is.
    for entry in parsed_blocks:
        if entry.get("type") != "item":
            continue
        if not entry.get("normalized_url"):
            keep_item_ids.add(int(entry["id"]))
            section_code = entry.get("section") or "??"
            kept_section_counts[section_code] = kept_section_counts.get(section_code, 0) + 1

    for grouped in url_groups.values():
        if len(grouped) == 1:
            chosen = grouped[0]
        else:
            chosen = max(
                grouped,
                key=lambda c: (
                    _fit_score(c),
                    -kept_section_counts.get(c.get("section") or "??", 0),
                    -raw_section_counts.get(c.get("section") or "??", 0),
                    _section_priority(c.get("section")),
                    -int(c["id"]),
                ),
            )

        keep_item_ids.add(int(chosen["id"]))
        section_code = chosen.get("section") or "??"
        kept_section_counts[section_code] = kept_section_counts.get(section_code, 0) + 1

        for entry in grouped:
            if entry is chosen:
                continue
            logger.warning(
                "Removed duplicate source URL in section %s (%s): %s; kept in section %s (%s): %s",
                (entry.get("section") or "??"),
                entry.get("title") or "",
                entry.get("source_url") or "",
                (chosen.get("section") or "??"),
                chosen.get("title") or "",
                chosen.get("source_url") or "",
            )

    removed = 0

    out: list[str] = []
    for entry in parsed_blocks:
        if entry.get("type") == "line":
            out.append(entry["line"])
            continue
        if int(entry["id"]) in keep_item_ids:
            out.extend(entry["block"])
        else:
            removed += 1

    if removed:
        logger.warning("Removed %d duplicate item(s) by source URL.", removed)
    return "\n".join(out)


def _prune_items_without_valid_source(markdown: str) -> str:
    """Remove generated items that do not contain a real source URL."""
    lines = markdown.splitlines()
    out: list[str] = []
    removed = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        title = _extract_item_title(line)
        if not title:
            out.append(line)
            i += 1
            continue

        block: list[str] = [line]
        i += 1
        while i < len(lines):
            next_line = lines[i]
            if _extract_section_code(next_line) or _extract_item_title(next_line):
                break
            block.append(next_line)
            i += 1

        if _item_has_valid_source_line(block):
            out.extend(block)
        else:
            removed += 1

    if removed:
        logger.warning("Pruned %d item(s) without valid source URL.", removed)
    return "\n".join(out)


def _render_source_line_html(stripped_line: str) -> str:
    url = _extract_url_from_related_link_line(stripped_line)
    if not url:
        return ""
    safe_url = escape(url)
    return (
        '<p><span style="color:#6b7280;font-size:13px;">相关链接：</span> '
        f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" '
        'style="color:#2563eb;font-weight:600;">阅读原文 -&gt;</a></p>'
    )


def _convert_inline_markdown_to_html(
    text: str,
    *,
    base_dir: Path,
    inline_images: dict[str, Path],
    use_cid_images: bool,
) -> str:
    def _replace_image(match: re.Match[str]) -> str:
        alt = escape(match.group(1) or "图片")
        src = (match.group(2) or "").strip()
        if src.startswith("http://") or src.startswith("https://"):
            return (
                f'<img src="{escape(src)}" alt="{alt}" '
                'style="max-width:100%;height:auto;border-radius:8px;margin:8px 0;" />'
            )

        local = (base_dir / "daily-news" / src).resolve()
        if local.exists() and local.is_file():
            if not use_cid_images:
                preview_src = f"daily-news/{src}"
                return (
                    f'<img src="{escape(preview_src)}" alt="{alt}" '
                    'style="max-width:100%;height:auto;border-radius:8px;margin:8px 0;" />'
                )
            cid = f"mynews-{len(inline_images) + 1}"
            inline_images[cid] = local
            return (
                f'<img src="cid:{cid}" alt="{alt}" '
                'style="max-width:100%;height:auto;border-radius:8px;margin:8px 0;" />'
            )

        # Missing local image: skip rendering this image line in email.
        return ""

    escaped = escape(text)
    escaped = _MARKDOWN_IMAGE_RE.sub(_replace_image, escaped)
    escaped = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        escaped,
    )
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def _contains_inline_html(text: str) -> bool:
    return re.search(r"</?[a-zA-Z][^>]*>", text) is not None


def _markdown_to_email_html(
    markdown_content: str,
    base_dir: Path,
    *,
    use_cid_images: bool,
) -> tuple[str, dict[str, Path]]:
    html_parts: list[str] = []
    inline_images: dict[str, Path] = {}
    for raw_line in markdown_content.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            html_parts.append("<div class=\"spacer\"></div>")
            continue

        if stripped.startswith("<") and stripped.endswith(">"):
            html_parts.append(stripped)
            continue

        if _is_source_line(stripped):
            source_html = _render_source_line_html(stripped)
            if source_html:
                html_parts.append(source_html)
            continue

        if _contains_inline_html(stripped):
            # Keep model-provided inline HTML styles (e.g. <span ...>) visible in email.
            html_parts.append(f"<p>{stripped}</p>")
            continue

        plain_section_match = _PLAIN_SECTION_TITLE_RE.match(stripped)
        if plain_section_match:
            section_code = plain_section_match.group(1)
            section_name = plain_section_match.group(2)
            html_parts.append(f"<h2>- {section_code} {escape(section_name)} -</h2>")
            continue

        if stripped.startswith("# "):
            html_parts.append(
                f"<h1>{_convert_inline_markdown_to_html(stripped[2:].strip(), base_dir=base_dir, inline_images=inline_images, use_cid_images=use_cid_images)}</h1>"
            )
            continue

        if stripped.startswith("## "):
            html_parts.append(
                f"<h2>{_convert_inline_markdown_to_html(stripped[3:].strip(), base_dir=base_dir, inline_images=inline_images, use_cid_images=use_cid_images)}</h2>"
            )
            continue

        if stripped.startswith("### "):
            html_parts.append(
                f"<h3>{_convert_inline_markdown_to_html(stripped[4:].strip(), base_dir=base_dir, inline_images=inline_images, use_cid_images=use_cid_images)}</h3>"
            )
            continue

        if stripped == "---":
            html_parts.append("<hr class=\"divider\" />")
            continue

        converted = _convert_inline_markdown_to_html(
            stripped,
            base_dir=base_dir,
            inline_images=inline_images,
            use_cid_images=use_cid_images,
        )
        if converted:
            html_parts.append(f"<p>{converted}</p>")

    return "\n".join(html_parts), inline_images


def render_my_news_email(
    markdown_content: str,
    base_dir: Path,
    *,
    use_cid_images: bool = True,
) -> tuple[str, str, dict[str, Path]]:
    """Render generated my-news markdown as a readable HTML email body."""
    first_heading = "TBK日报"
    report_date = datetime.now(_BJT).strftime("%Y年%m月%d日")
    for line in markdown_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            first_heading = stripped[2:].strip()
            report_date = stripped[2:].split(" ", 1)[0]
            break

    content_html, inline_images = _markdown_to_email_html(
        markdown_content,
        base_dir,
        use_cid_images=use_cid_images,
    )
    template = _env.get_template("my_news_email.html")
    html_body = template.render(
        subject=first_heading,
        date=report_date,
        content_html=content_html,
    )
    return first_heading, html_body, inline_images


def _extract_representative_image_url(article_url: str) -> str | None:
    try:
        resp = requests.get(article_url, timeout=DEEPSEEK_TIMEOUT)
        resp.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    selectors = [
        ('meta[property="og:image"]', "content"),
        ('meta[name="twitter:image"]', "content"),
        ('link[rel="image_src"]', "href"),
    ]
    for selector, attr in selectors:
        tag = soup.select_one(selector)
        value = (tag.get(attr) if tag else "") or ""
        if value and not value.startswith("data:"):
            return urljoin(article_url, value)

    for img in soup.select("article img[src], main img[src], img[src]"):
        src = (img.get("src") or "").strip()
        if src and not src.startswith("data:"):
            return urljoin(article_url, src)
    return None


def _download_image(image_url: str, target_file: Path) -> str | None:
    try:
        resp = requests.get(image_url, timeout=DEEPSEEK_TIMEOUT)
        resp.raise_for_status()
    except Exception:
        return None
    if not resp.content:
        return None
    target_file.write_bytes(resp.content)
    return resp.headers.get("Content-Type", "")


def _process_images_for_markdown(
    markdown: str,
    images_dir: Path,
    bjt_now: datetime,
) -> str:
    lines = markdown.splitlines()
    section_counts: dict[str, int] = {}
    current_section: str | None = None
    item: dict | None = None
    updates: list[tuple[int, str, int | None]] = []

    for i, line in enumerate(lines):
        section = _extract_section_code(line)
        if section:
            current_section = section
            continue

        stripped = line.strip()
        item_title = _extract_item_title(line)
        if item_title:
            item = {
                "section": current_section,
                "title_idx": i,
                "image_idx": None,
                "title": item_title,
            }
            continue

        if not item:
            continue

        if stripped.startswith("![") and "](" in stripped and item["image_idx"] is None:
            item["image_idx"] = i
            continue

        if _is_source_line(stripped):
            section = item.get("section")
            url = _extract_url_from_related_link_line(stripped)
            if section and url:
                seq = section_counts.get(section, 0) + 1
                section_counts[section] = seq

                image_url = _extract_representative_image_url(url)
                if image_url:
                    ext = _get_image_extension(image_url, "")
                    image_file_name = f"{bjt_now:%Y%m%d}_{section}_{seq}.{ext}"
                    image_file = images_dir / image_file_name
                    content_type = _download_image(image_url, image_file)
                    if content_type is not None:
                        real_ext = _get_image_extension(image_url, content_type)
                        if real_ext != ext:
                            real_file_name = f"{bjt_now:%Y%m%d}_{section}_{seq}.{real_ext}"
                            real_file = images_dir / real_file_name
                            image_file.rename(real_file)
                            image_file_name = real_file_name
                        alt_text = re.sub(r"[\[\]\(\)]", "", str(item.get("title", ""))).strip()
                        if not alt_text:
                            alt_text = "代表图"
                        image_line = f"![{alt_text}](images/{image_file_name})"
                        title_idx = int(item.get("title_idx", i))
                        image_idx_raw = item.get("image_idx")
                        image_idx = int(image_idx_raw) if image_idx_raw is not None else None
                        updates.append((title_idx, image_line, image_idx))
                        logger.info(
                            "Downloaded image for section %s #%d: %s",
                            section,
                            seq,
                            image_file_name,
                        )
                    else:
                        logger.warning(
                            "Failed to download representative image for %s", url
                        )
                else:
                    logger.info("No representative image found for %s", url)
            item = None

    for title_idx, image_line, image_idx in reversed(updates):
        if image_idx is not None:
            lines[image_idx] = image_line
        else:
            lines.insert(title_idx + 1, "")
            lines.insert(title_idx + 2, image_line)

    return "\n".join(lines)


def _ensure_daily_news_dirs(base_dir: Path) -> tuple[Path, Path]:
    daily_news_dir = base_dir / "daily-news"
    images_dir = daily_news_dir / "images"
    daily_news_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    return daily_news_dir, images_dir


def _current_bjt_for_filename(now_utc: datetime | None = None) -> datetime:
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    return now_utc.astimezone(_BJT)


def _daily_news_filepath(base_dir: Path, now_utc: datetime | None = None) -> Path:
    daily_news_dir, _ = _ensure_daily_news_dirs(base_dir)
    bjt_now = _current_bjt_for_filename(now_utc)
    file_name = bjt_now.strftime("%Y%m%d%H%M_daily_news.md")
    return daily_news_dir / file_name


def load_my_news_markdown_for_sending(
    base_dir: Path,
    *,
    now_utc: datetime | None = None,
    preferred_file: Path | None = None,
) -> tuple[Path, str]:
    """Load markdown for send-only flow.

    Priority:
    1) preferred_file if provided;
    2) latest file for today's BJT date (YYYYMMDD*_daily_news.md).
    """
    daily_news_dir, _ = _ensure_daily_news_dirs(base_dir)

    if preferred_file is not None:
        target = preferred_file.expanduser().resolve()
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"my-news markdown file not found: {target}")
        return target, target.read_text(encoding="utf-8")

    bjt_now = _current_bjt_for_filename(now_utc)
    pattern = f"{bjt_now:%Y%m%d}*_daily_news.md"
    candidates = sorted(daily_news_dir.glob(pattern))
    if not candidates:
        raise FileNotFoundError(
            "No generated my-news markdown found for today (BJT). "
            f"Expected under: {daily_news_dir} with pattern: {pattern}"
        )

    target = candidates[-1]
    return target, target.read_text(encoding="utf-8")


def _published_concepts_file(base_dir: Path) -> Path:
    daily_news_dir, _ = _ensure_daily_news_dirs(base_dir)
    return daily_news_dir / "published_concepts.md"


def _read_published_concepts(base_dir: Path) -> str:
    concepts_file = _published_concepts_file(base_dir)
    if not concepts_file.exists():
        return ""
    return concepts_file.read_text(encoding="utf-8")


def _extract_methodology_concept(markdown: str) -> str | None:
    lines = markdown.splitlines()
    in_methodology = False
    for line in lines:
        text = line.strip()
        section = _extract_section_code(text)
        if section:
            in_methodology = section == "05"
            if not in_methodology:
                continue
            continue

        if not in_methodology:
            continue

        if text.startswith("**") and text.endswith("**") and len(text) > 4:
            return text.strip("*").strip()

        md_item = _MARKDOWN_ITEM_RE.match(text)
        if md_item:
            return md_item.group(1).strip()
    return None


def _append_published_concept(base_dir: Path, concept: str | None) -> None:
    if not concept:
        return
    concepts_file = _published_concepts_file(base_dir)
    concept_line = f"- {concept}"
    if concepts_file.exists():
        existing_lines = {
            line.strip() for line in concepts_file.read_text(encoding="utf-8").splitlines()
        }
        if concept_line in existing_lines:
            return
    with concepts_file.open("a", encoding="utf-8") as fh:
        fh.write(f"{concept_line}\n")


def _extract_intro_section_fallbacks(markdown: str) -> dict[str, str]:
    """Extract intro summaries like '03 核心论文：...' for empty-section fallback."""
    lines = markdown.splitlines()
    in_intro = False
    fallback_by_section: dict[str, str] = {}

    for line in lines:
        stripped = line.strip()
        section = _extract_section_code(stripped)
        if section is not None:
            if in_intro:
                break
            continue

        if "导读" in stripped:
            in_intro = True
            continue

        if not in_intro:
            continue

        plain = re.sub(r"<[^>]+>", "", stripped).strip()
        if not plain:
            continue

        match = _INTRO_SECTION_LINE_RE.match(plain)
        if not match:
            continue

        code = match.group(1)
        summary = match.group(2).strip()
        if summary:
            fallback_by_section[code] = summary

    return fallback_by_section


def _section_has_content(section_block: list[str]) -> bool:
    # Skip the section title line itself.
    for line in section_block[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if _extract_item_title(line):
            return True
        if _is_source_line(stripped):
            return True

        plain = re.sub(r"<[^>]+>", "", stripped).strip()
        if plain:
            return True

    return False


def _fill_empty_sections_from_intro(markdown: str) -> str:
    """Fill empty numbered sections using intro summaries to keep email layout stable."""
    fallbacks = _extract_intro_section_fallbacks(markdown)
    if not fallbacks:
        return markdown

    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    filled = 0

    while i < len(lines):
        line = lines[i]
        section = _extract_section_code(line)
        if not section:
            out.append(line)
            i += 1
            continue

        block: list[str] = [line]
        i += 1
        while i < len(lines):
            next_line = lines[i]
            if _extract_section_code(next_line):
                break
            block.append(next_line)
            i += 1

        if not _section_has_content(block):
            fallback = (fallbacks.get(section) or "").strip()
            if fallback:
                if block and block[-1].strip():
                    block.append("")
                block.append(fallback)
                filled += 1

        out.extend(block)

    if filled:
        logger.info("Filled %d empty section(s) from intro summaries.", filled)
    return "\n".join(out)


def _repair_numbered_section_structure(markdown: str) -> str:
    """Repair malformed numbered section wrappers and missing separators."""
    lines = markdown.splitlines()
    section_header_line_re = re.compile(r"^\s*(<h3>-\s*(\d{2})\s+.+\s*-</h3>)\s*$")
    numbered_codes = {f"{n:02d}" for n in range(1, 8)}

    # Pass 1: ensure every numbered <h3> has <div align="center"> wrapper.
    normalized: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        match = section_header_line_re.match(line)
        if not match or match.group(2) not in numbered_codes:
            normalized.append(line)
            i += 1
            continue

        header_line = f"  {match.group(1)}"

        prev_non_empty = next((x.strip() for x in reversed(normalized) if x.strip()), "")
        if prev_non_empty != '<div align="center">':
            normalized.append('<div align="center">')

        normalized.append(header_line)

        next_stripped = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if next_stripped == "</div>":
            normalized.append("</div>")
            i += 2
        else:
            normalized.append("</div>")
            i += 1

    # Pass 2: ensure numbered sections are separated by `---`.
    repaired: list[str] = []
    idx = 0
    while idx < len(normalized):
        current = normalized[idx]
        stripped = current.strip()

        is_numbered_section_div = False
        if stripped == '<div align="center">':
            lookahead = idx + 1
            while lookahead < len(normalized) and not normalized[lookahead].strip():
                lookahead += 1
            if lookahead < len(normalized):
                code = _extract_section_code(normalized[lookahead])
                is_numbered_section_div = code in numbered_codes

        if is_numbered_section_div:
            prev_non_empty = next((x.strip() for x in reversed(repaired) if x.strip()), "")
            if prev_non_empty and prev_non_empty != "---":
                if repaired and repaired[-1].strip():
                    repaired.append("")
                repaired.append("---")
                repaired.append("")

        repaired.append(current)
        idx += 1

    return "\n".join(repaired)


def _build_messages(
    prompt_text: str,
    published_concepts: str,
    bjt_now: datetime,
    source_context: str,
) -> list[dict]:
    extra_rule = (
        "下面是 historical published concepts，用于“每日方法论”去重。"
        "若为空表示暂无历史：\n"
        f"{published_concepts or '(empty)'}"
    )
    return [
        {"role": "system", "content": prompt_text},
        {
            "role": "user",
            "content": (
                "请生成今天的完整日报，并严格遵守所有结构和数量要求。"
                f"今天北京时间是 {bjt_now:%Y-%m-%d}，标题日期必须使用这一天。"
                "相关链接必须优先使用我提供的‘可信来源URL列表’，禁止虚构链接。"
                "同一个相关链接URL在整篇日报中只能出现一次，禁止重复用于不同条目。"
                "相关链接必须是真实、可访问的 HTTP/HTTPS URL，禁止虚构或占位链接。"
                "任何没有原始URL的条目都不要输出；宁缺毋滥。"
                "严禁输出‘链接缺失（请人工补充）’这类占位文本。"
                "只输出最终 Markdown 内容，不要输出任何过程说明或前言。"
            ),
        },
        {
            "role": "user",
            "content": (
                "下面是今天抓取到的可信来源URL清单（含标题），生成内容时请优先引用这些URL：\n"
                f"{source_context}"
            ),
        },
        {"role": "user", "content": extra_rule},
    ]


def _collect_trusted_sources_for_prompt(
    now_utc: datetime,
    max_items: int = 80,
) -> tuple[str, set[str]]:
    lines: list[str] = []
    allowed_urls: set[str] = set()
    window_start_utc, window_end_utc = _get_report_window(now_utc)
    try:
        from src.fetchers.news_fetcher import fetch_all_news

        news_items = _filter_items_for_window(
            fetch_all_news(),
            window_start_utc,
            window_end_utc,
        )
        for item in news_items:
            url = (item.get("url") or "").strip()
            title = (item.get("title") or "").strip()
            if not url or url in allowed_urls:
                continue
            allowed_urls.add(url)
            lines.append(f"- {title} | {url}")
            if len(lines) >= max_items:
                break
    except Exception as exc:
        logger.warning("Failed to collect RSS trusted sources: %s", exc)

    try:
        from src.fetchers.twitter_fetcher import fetch_all_tweets

        tweet_items = _filter_items_for_window(
            fetch_all_tweets(),
            window_start_utc,
            window_end_utc,
        )
        for item in tweet_items:
            url = (item.get("url") or "").strip()
            text = (item.get("text") or "").strip().replace("\n", " ")
            if not url or url in allowed_urls:
                continue
            allowed_urls.add(url)
            lines.append(f"- Tweet: {text[:80]} | {url}")
            if len(lines) >= max_items:
                break
    except Exception as exc:
        logger.warning("Failed to collect Twitter trusted sources: %s", exc)

    source_context = "\n".join(lines) if lines else "(empty)"
    logger.info(
        "Trusted source window mode=%s [%s, %s): %d URL(s)",
        (REPORT_WINDOW_MODE or "anchored").strip().lower(),
        window_start_utc.isoformat(),
        window_end_utc.isoformat(),
        len(allowed_urls),
    )
    return source_context, allowed_urls


def prepare_my_news_generation_context(
    base_dir: Path,
    now_utc: datetime | None = None,
) -> MyNewsGenerationContext:
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is not set.")

    now_utc = now_utc or datetime.now(timezone.utc)
    bjt_now = _current_bjt_for_filename(now_utc)
    published_concepts = _read_published_concepts(base_dir)
    prompt_text = get_my_news_prompt(base_dir)
    source_context, allowed_urls = _collect_trusted_sources_for_prompt(now_utc)
    messages = _build_messages(
        prompt_text,
        published_concepts,
        bjt_now,
        source_context,
    )
    return MyNewsGenerationContext(
        now_utc=now_utc,
        bjt_now=bjt_now,
        messages=messages,
        allowed_urls=allowed_urls,
    )


def build_my_news_retry_messages(
    base_messages: list[dict],
    failed_markdown: str,
    marker: str,
) -> list[dict]:
    retry_messages = [dict(message) for message in base_messages]
    retry_messages.extend(
        [
            {"role": "assistant", "content": failed_markdown},
            {
                "role": "user",
                "content": (
                    f"上一次输出未通过校验，因为缺少必需标记：{marker}。"
                    "请基于上一次草稿直接修正，不要重写执行计划，不要输出过程说明。"
                    "请尽量保留已有真实链接和内容，只修正结构，使标题后尽快进入导读模块。"
                ),
            },
        ]
    )
    return retry_messages


def generate_my_news_candidate_markdown(
    messages: list[dict],
    bjt_now: datetime,
) -> tuple[str, str | None]:
    content, finish_reason = _generate_with_continuation(messages)
    if not content:
        raise RuntimeError("DeepSeek returned empty content.")
    content = _strip_model_preface(content)
    content = _normalize_report_title_date(content, bjt_now)
    content = _strip_generation_chatter(content)
    if finish_reason in ("length", "max_tokens"):
        logger.warning(
            "Model output remained truncated after continuation attempts; proceeding with partial content."
        )
    return content, finish_reason


def finalize_my_news_markdown(
    base_dir: Path,
    markdown: str,
    allowed_urls: set[str],
    *,
    now_utc: datetime,
    bjt_now: datetime,
) -> tuple[Path, str]:
    content = markdown
    content = _strip_paragraph_labels(content)
    content = _convert_scores_to_stars(content)
    content = _sanitize_related_links(
        content,
        allowed_urls=allowed_urls if allowed_urls else None,
    )
    if MY_NEWS_PRUNE_INVALID_SOURCE_ITEMS:
        content = _prune_items_without_valid_source(content)
    else:
        logger.info(
            "Skip pruning items without valid source URL "
            "(MY_NEWS_PRUNE_INVALID_SOURCE_ITEMS=false)."
        )
    content = _enforce_core_paper_source_domains(content)
    content = _fill_empty_sections_from_intro(content)
    content = _dedupe_items_by_source_url(content)
    content = _ensure_core_paper_fallback_text(content)
    _, images_dir = _ensure_daily_news_dirs(base_dir)
    content = _process_images_for_markdown(content, images_dir, bjt_now)
    content = _repair_numbered_section_structure(content)
    output_file = _daily_news_filepath(base_dir, now_utc=now_utc)
    output_file.write_text(content, encoding="utf-8")
    concept = _extract_methodology_concept(content)
    _append_published_concept(base_dir, concept)
    return output_file, content


def generate_my_news_markdown(
    base_dir: Path, now_utc: datetime | None = None
) -> tuple[Path, str]:
    context = prepare_my_news_generation_context(base_dir, now_utc=now_utc)
    content, _ = generate_my_news_candidate_markdown(context.messages, context.bjt_now)
    return finalize_my_news_markdown(
        base_dir,
        content,
        context.allowed_urls,
        now_utc=context.now_utc,
        bjt_now=context.bjt_now,
    )

