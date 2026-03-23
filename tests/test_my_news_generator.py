from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src import my_news_generator
from src.my_news_generator import (
    _dedupe_items_by_source_url,
    _fill_empty_sections_from_intro,
    _generate_with_continuation,
    _convert_scores_to_stars,
    _daily_news_filepath,
    _extract_url_from_related_link_line,
    _extract_methodology_concept,
    _get_image_extension,
    _normalize_url_for_dedupe,
    _normalize_report_title_date,
    _process_images_for_markdown,
    _prune_items_without_valid_source,
    _sanitize_related_links,
    _strip_paragraph_labels,
    _strip_generation_chatter,
    _strip_model_preface,
    build_my_news_retry_messages,
    finalize_my_news_markdown,
    load_my_news_markdown_for_sending,
    render_my_news_email,
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


def test_normalize_url_for_dedupe_removes_tracking_and_fragment():
    raw = "https://Example.com/path/?utm_source=x&b=2&a=1&fbclid=abc#part"
    normalized = _normalize_url_for_dedupe(raw)
    assert normalized == "https://example.com/path?a=1&b=2"


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
    assert "![案例A 8.9](images/20260323_01_1.jpg)" in output
    assert (tmp_path / "20260323_01_1.jpg").exists()


def test_process_images_for_markdown_supports_markdown_headers_and_source(monkeypatch, tmp_path):
    markdown = """
## 01 AI编程

### 1. Claude Code企业实践

来源：https://example.com/a
""".strip()

    monkeypatch.setattr(
        my_news_generator,
        "_extract_representative_image_url",
        lambda url: "https://cdn.example.com/cover.png",
    )

    def fake_download(image_url, target_file):
        target_file.write_bytes(b"fake")
        return "image/png"

    monkeypatch.setattr(my_news_generator, "_download_image", fake_download)

    bjt_now = datetime(2026, 3, 23, 10, 38, tzinfo=timezone.utc).astimezone(
        timezone(timedelta(hours=8))
    )
    output = _process_images_for_markdown(markdown, tmp_path, bjt_now)
    assert "![Claude Code企业实践](images/20260323_01_1.png)" in output
    assert (tmp_path / "20260323_01_1.png").exists()


def test_title_date_and_preface_are_normalized_to_bjt():
    raw = "我将为您生成日报\n\n# 2026年3月22日 TBK日报：看见世界、发现自己\n\n正文"
    bjt_now = datetime(2026, 3, 23, 2, 38, tzinfo=timezone.utc).astimezone(
        timezone(timedelta(hours=8))
    )
    trimmed = _strip_model_preface(raw)
    normalized = _normalize_report_title_date(trimmed, bjt_now)
    assert normalized.startswith("# 2026年3月23日 TBK日报：看见世界、发现自己")


def test_convert_scores_to_stars_uses_half_star_step():
    text = "A [[8.0/10]] B [[9/10]] C [[10/10]]"
    output = _convert_scores_to_stars(text)
    assert "A [★★★★☆]" in output
    assert "B [★★★★⯨]" in output
    assert "C [★★★★★]" in output


def test_render_my_news_email_uses_title_as_subject(tmp_path):
    markdown = "# 2026年3月23日 TBK日报：看见世界、发现自己\n\n正文"
    subject, html, inline_images = render_my_news_email(markdown, tmp_path)
    assert subject == "2026年3月23日 TBK日报：看见世界、发现自己"
    assert "TBK 日报" in html
    assert "<p>正文</p>" in html
    assert inline_images == {}


def test_render_my_news_email_preserves_inline_span_html(tmp_path):
    markdown = "# 标题\n\n<span style=\"color:#d97a5b\">01 AI编程：</span> 摘要"
    _, html, _ = render_my_news_email(markdown, tmp_path)
    assert "<span style=\"color:#d97a5b\">01 AI编程：</span> 摘要" in html


def test_render_my_news_email_converts_local_images_to_cid(tmp_path):
    images_dir = tmp_path / "daily-news" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / "x.jpg").write_bytes(b"fake")

    markdown = "# 标题\n\n![示意图](images/x.jpg)"
    _, html, inline_images = render_my_news_email(markdown, tmp_path)
    assert "cid:mynews-1" in html
    assert "mynews-1" in inline_images


def test_render_my_news_email_preview_keeps_local_image_path(tmp_path):
    images_dir = tmp_path / "daily-news" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / "x.jpg").write_bytes(b"fake")

    markdown = "# 标题\n\n![示意图](images/x.jpg)"
    _, html, inline_images = render_my_news_email(
        markdown,
        tmp_path,
        use_cid_images=False,
    )
    assert "daily-news/images/x.jpg" in html
    assert inline_images == {}


def test_render_my_news_email_hides_missing_local_images(tmp_path):
    markdown = "# 标题\n\n![示意图](images/missing.jpg)\n\n正文"
    _, html, inline_images = render_my_news_email(markdown, tmp_path)
    assert "图片缺失" not in html
    assert inline_images == {}


def test_render_my_news_email_formats_source_line_as_read_more_link(tmp_path):
    markdown = "# 标题\n\n**相关链接：** https://example.com/a"
    _, html, _ = render_my_news_email(markdown, tmp_path)
    assert "阅读原文 -&gt;" in html
    assert 'href="https://example.com/a"' in html


def test_sanitize_related_links_replaces_unreachable(monkeypatch):
    markdown = "**相关链接：** https://bad.example.com/a"
    monkeypatch.setattr(my_news_generator, "_is_url_reachable", lambda url: False)
    output = _sanitize_related_links(markdown)
    assert output.strip() == "**相关链接：** [阅读原文 ->](https://bad.example.com/a)"


def test_sanitize_related_links_keeps_reachable(monkeypatch):
    markdown = "**相关链接：** https://ok.example.com/a"
    monkeypatch.setattr(my_news_generator, "_is_url_reachable", lambda url: True)
    output = _sanitize_related_links(markdown)
    assert output.strip() == "**相关链接：** [阅读原文 ->](https://ok.example.com/a)"


def test_sanitize_related_links_keeps_original_when_status_unknown(monkeypatch):
    markdown = "**相关链接：** https://unknown.example.com/a"
    monkeypatch.setattr(my_news_generator, "_is_url_reachable", lambda url: None)
    output = _sanitize_related_links(markdown)
    assert output.strip() == "**相关链接：** [阅读原文 ->](https://unknown.example.com/a)"


def test_sanitize_related_links_rejects_untrusted_url(monkeypatch):
    markdown = "**相关链接：** https://not-in-list.example.com/a"
    monkeypatch.setattr(my_news_generator, "_is_url_reachable", lambda url: True)
    output = _sanitize_related_links(markdown, allowed_urls={"https://ok.example.com/a"})
    assert output.strip() == "**相关链接：** [阅读原文 ->](https://not-in-list.example.com/a)"


def test_strip_paragraph_labels_removes_glm_prefix():
    markdown = "[正文段落]：第一段\n【正文段落】: 第二段\n[正文]：第三段\n【正文】: 第四段"
    output = _strip_paragraph_labels(markdown)
    assert output.splitlines() == ["第一段", "第二段", "第三段", "第四段"]


def test_dedupe_items_by_source_url_prefers_section_balance_when_intro_fit_ties():
    markdown = """
## 02 AI应用案例

### 1. 重复链接-错误分类
正文A
**相关链接：** https://example.com/shared

### 2. 另一个应用案例
正文B
**相关链接：** https://example.com/b

## 04 前瞻观点

### 1. 重复链接-更合适分类
正文C
**相关链接：** https://example.com/shared
""".strip()

    output = _dedupe_items_by_source_url(markdown)
    assert "另一个应用案例" in output
    assert "重复链接-更合适分类" in output
    assert "重复链接-错误分类" not in output


def test_prune_items_without_valid_source_drops_invalid_item():
    markdown = """
## 01 AI编程

### 1. 有效条目
正文
**相关链接：** https://example.com/a

### 2. 无效条目
正文
**相关链接：** 链接缺失（请人工补充）
""".strip()
    output = _prune_items_without_valid_source(markdown)
    assert "有效条目" in output
    assert "无效条目" not in output


def test_dedupe_items_by_source_url_keeps_first_item_across_sections():
    markdown = """
## 01 AI编程

### 1. 第一条
正文A
**相关链接：** https://example.com/a?utm_source=feed

## 02 AI产品

### 1. 第二条
正文B
**相关链接：** https://example.com/a
""".strip()
    output = _dedupe_items_by_source_url(markdown)
    assert "第一条" in output
    assert "第二条" not in output


def test_fill_empty_sections_from_intro_for_core_paper_section():
    markdown = """
# 标题

<div align="center">
  <h3>- 导读 -</h3>
</div>

<span style="color:#d97a5b">03 核心论文：</span> 今日暂无符合标准的学术论文资讯（需从arXiv、Nature等核心学术源获取）

<div align="center">
  <h3>- 03 核心论文 -</h3>
</div>

<div align="center">
  <h3>- 04 前瞻观点 -</h3>
</div>

### 1. 某观点
正文
**相关链接：** https://example.com/b
""".strip()
    output = _fill_empty_sections_from_intro(markdown)
    assert "- 03 核心论文 -" in output
    assert "今日暂无符合标准的学术论文资讯" in output


def test_strip_generation_chatter_removes_plan_lines():
    raw = """
# 2026年3月23日 TBK日报：看见世界、发现自己

我将开始为您生成2026年3月23日的TBK日报。
1. 首先创建目录结构
2. 读取去重文件

<div align="center">
  <h3>- 导读 -</h3>
</div>
""".strip()
    cleaned = _strip_generation_chatter(raw)
    assert "我将开始为您生成" not in cleaned
    assert "首先创建目录结构" not in cleaned
    assert "<h3>- 导读 -</h3>" in cleaned


def test_generate_with_continuation_merges_chunks(monkeypatch):
    calls = {"n": 0}

    def fake_call(messages):
        calls["n"] += 1
        if calls["n"] == 1:
            return "第一段", "max_tokens"
        return "第二段", "stop"

    monkeypatch.setattr(my_news_generator, "_call_llm_api", fake_call)
    content, finish = _generate_with_continuation([{"role": "user", "content": "x"}], max_rounds=3)
    assert "第一段" in content and "第二段" in content
    assert finish == "stop"


def test_build_my_news_retry_messages_keeps_failed_draft_as_assistant_history():
    base_messages = [{"role": "user", "content": "seed"}]
    messages = build_my_news_retry_messages(base_messages, "失败草稿", "- 导读 -")
    assert messages[0] == {"role": "user", "content": "seed"}
    assert messages[-2] == {"role": "assistant", "content": "失败草稿"}
    assert "- 导读 -" in messages[-1]["content"]


def test_finalize_my_news_markdown_processes_images_only_at_finalize(monkeypatch, tmp_path):
    calls = {"images": 0}

    monkeypatch.setattr(
        my_news_generator,
        "_process_images_for_markdown",
        lambda markdown, images_dir, bjt_now: calls.__setitem__("images", calls["images"] + 1) or markdown,
    )

    markdown = "# 2026年3月23日 TBK日报：看见世界、发现自己\n\n<div align=\"center\"><h3>- 导读 -</h3></div>\n\n**标题**\n\n**相关链接：** https://example.com/a"
    output_file, output_markdown = finalize_my_news_markdown(
        tmp_path,
        markdown,
        {"https://example.com/a"},
        now_utc=datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc),
        bjt_now=datetime(2026, 3, 23, 8, 0, tzinfo=timezone(timedelta(hours=8))),
    )

    assert calls["images"] == 1
    assert output_file.exists()
    assert "https://example.com/a" in output_markdown


def test_finalize_my_news_markdown_dedupes_duplicate_source_url(monkeypatch, tmp_path):
    monkeypatch.setattr(
        my_news_generator,
        "_process_images_for_markdown",
        lambda markdown, images_dir, bjt_now: markdown,
    )

    markdown = """
# 2026年3月23日 TBK日报：看见世界、发现自己

## 01 AI编程

### 1. 条目A
正文A
**相关链接：** https://example.com/a?utm_medium=x

## 02 AI产品

### 1. 条目B
正文B
**相关链接：** https://example.com/a
""".strip()

    _, output_markdown = finalize_my_news_markdown(
        tmp_path,
        markdown,
        {"https://example.com/a", "https://example.com/a?utm_medium=x"},
        now_utc=datetime(2026, 3, 23, 0, 0, tzinfo=timezone.utc),
        bjt_now=datetime(2026, 3, 23, 8, 0, tzinfo=timezone(timedelta(hours=8))),
    )

    assert "条目A" in output_markdown
    assert "条目B" not in output_markdown


def test_load_my_news_markdown_for_sending_prefers_latest_today_file(tmp_path):
    daily_news_dir = tmp_path / "daily-news"
    daily_news_dir.mkdir(parents=True, exist_ok=True)
    older = daily_news_dir / "202603230801_daily_news.md"
    newer = daily_news_dir / "202603230830_daily_news.md"
    older.write_text("older", encoding="utf-8")
    newer.write_text("newer", encoding="utf-8")

    file_path, content = load_my_news_markdown_for_sending(
        tmp_path,
        now_utc=datetime(2026, 3, 23, 1, 0, tzinfo=timezone.utc),
    )

    assert file_path.name == "202603230830_daily_news.md"
    assert content == "newer"


