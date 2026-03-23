from __future__ import annotations

from datetime import datetime, timezone

from src.my_news_generator import (
    _daily_news_filepath,
    _extract_methodology_concept,
)


def test_daily_news_filepath_uses_beijing_time(tmp_path):
    now_utc = datetime(2026, 3, 22, 2, 27, tzinfo=timezone.utc)  # BJT 10:27
    path = _daily_news_filepath(tmp_path, now_utc)
    assert path.name == "202603221027_daily_news.md"
    assert path.parent.name == "daily-news"


def test_extract_methodology_concept_from_markdown():
    markdown = """
<div align="center">
  <h3>- 05 每日方法论 -</h3>
</div>

**系统1与系统2**

一些正文...
"""
    concept = _extract_methodology_concept(markdown)
    assert concept == "系统1与系统2"

