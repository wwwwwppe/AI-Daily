from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src import my_news_generator
from src.my_news_generator import (
    _daily_news_filepath,
    _extract_url_from_related_link_line,
    _extract_methodology_concept,
    _get_image_extension,
    _process_images_for_markdown,
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


def test_extract_url_from_related_link_line():
    line = "**相关链接：** [https://example.com/a](https://example.com/a)"
    assert _extract_url_from_related_link_line(line) == "https://example.com/a"
    assert _extract_url_from_related_link_line("**相关链接：** https://example.com/b") == "https://example.com/b"


def test_get_image_extension_prefers_known_path_extension():
    assert _get_image_extension("https://example.com/img.webp", "") == "webp"
    assert _get_image_extension("https://example.com/img", "image/png") == "png"


def test_process_images_for_markdown_downloads_and_replaces(monkeypatch, tmp_path):
    markdown = """
<div align="center">
  <h3>- 01 AI编程 -</h3>
</div>

**案例A [[8.9]]**

[正文]

**相关链接：** https://example.com/article-a
""".strip()

    monkeypatch.setattr(
        my_news_generator,
        "_extract_representative_image_url",
        lambda url: "https://cdn.example.com/a.jpg",
    )

    def fake_download(image_url, target_file):
        target_file.write_bytes(b"fake")
        return "image/jpeg"

    monkeypatch.setattr(my_news_generator, "_download_image", fake_download)

    bjt_now = datetime(2026, 3, 23, 10, 27, tzinfo=timezone.utc).astimezone(
        timezone(timedelta(hours=8))
    )
    output = _process_images_for_markdown(markdown, tmp_path, bjt_now)
    assert "![案例A [[8.9]]](images/20260323_01_1.jpg)" in output
    assert (tmp_path / "20260323_01_1.jpg").exists()
