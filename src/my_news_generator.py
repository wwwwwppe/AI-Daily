"""
src/my_news_generator.py  –  Generate my-news markdown via DeepSeek API.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_API_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_TIMEOUT,
)
from src.skills import MY_NEWS_PROMPT


_BJT = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)
_SECTION_HEADER_RE = re.compile(r"<h3>-\s*(\d{2})\s+.+\s*-</h3>")


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


def _is_item_title_line(stripped: str) -> bool:
    return (
        stripped.startswith("**")
        and stripped.endswith("**")
        and not stripped.startswith("**相关链接：**")
    )


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
        section_match = _SECTION_HEADER_RE.search(line)
        if section_match:
            current_section = section_match.group(1)
            continue

        stripped = line.strip()
        if _is_item_title_line(stripped):
            item = {
                "section": current_section,
                "title_idx": i,
                "image_idx": None,
                "title": stripped.strip("*").strip(),
            }
            continue

        if not item:
            continue

        if stripped.startswith("![") and "](" in stripped and item["image_idx"] is None:
            item["image_idx"] = i
            continue

        if stripped.startswith("**相关链接：**"):
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
                        image_line = f"![{item['title']}](images/{image_file_name})"
                        updates.append((item["title_idx"], image_line, item["image_idx"]))
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


def _published_concepts_file(base_dir: Path) -> Path:
    daily_news_dir, _ = _ensure_daily_news_dirs(base_dir)
    return daily_news_dir / "published_concepts.md"


def _read_published_concepts(base_dir: Path) -> str:
    concepts_file = _published_concepts_file(base_dir)
    if not concepts_file.exists():
        return ""
    return concepts_file.read_text(encoding="utf-8")


def _extract_methodology_concept(markdown: str) -> str | None:
    marker = '<h3>- 05 每日方法论 -</h3>'
    idx = markdown.find(marker)
    if idx == -1:
        return None
    after_lines = markdown[idx:].splitlines()
    for line in after_lines[1:21]:
        text = line.strip()
        if text.startswith("**") and text.endswith("**") and len(text) > 4:
            return text.strip("*").strip()
        section_match = _SECTION_HEADER_RE.search(text)
        if section_match and section_match.group(1) != "05":
            break
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


def _build_messages(published_concepts: str) -> list[dict]:
    extra_rule = (
        "下面是 historical published concepts，用于“每日方法论”去重。"
        "若为空表示暂无历史：\n"
        f"{published_concepts or '(empty)'}"
    )
    return [
        {"role": "system", "content": MY_NEWS_PROMPT},
        {"role": "user", "content": "请生成今天的完整日报，并严格遵守所有结构和数量要求。"},
        {"role": "user", "content": extra_rule},
    ]


def generate_my_news_markdown(
    base_dir: Path, now_utc: datetime | None = None
) -> tuple[Path, str]:
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is not set.")

    published_concepts = _read_published_concepts(base_dir)
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": _build_messages(published_concepts),
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        DEEPSEEK_API_URL,
        headers=headers,
        json=payload,
        timeout=DEEPSEEK_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )
    if not content:
        raise RuntimeError("DeepSeek returned empty content.")

    bjt_now = _current_bjt_for_filename(now_utc)
    _, images_dir = _ensure_daily_news_dirs(base_dir)
    content = _process_images_for_markdown(content, images_dir, bjt_now)
    output_file = _daily_news_filepath(base_dir, now_utc=now_utc)
    output_file.write_text(content, encoding="utf-8")
    concept = _extract_methodology_concept(content)
    _append_published_concept(base_dir, concept)
    return output_file, content
