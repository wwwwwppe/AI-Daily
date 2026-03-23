"""
src/my_news_generator.py  –  Generate my-news markdown via DeepSeek API.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from src.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_API_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_TIMEOUT,
)
from src.skills import MY_NEWS_PROMPT


_BJT = timezone(timedelta(hours=8))


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
        if text.startswith('<h3>- 06 ') or text.startswith('<h3>- 07 '):
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


def generate_my_news_markdown(base_dir: Path) -> tuple[Path, str]:
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

    output_file = _daily_news_filepath(base_dir)
    output_file.write_text(content, encoding="utf-8")
    concept = _extract_methodology_concept(content)
    _append_published_concept(base_dir, concept)
    return output_file, content
