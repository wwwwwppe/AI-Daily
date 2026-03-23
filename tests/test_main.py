from __future__ import annotations

from datetime import datetime, timezone

from main import (
    _MAX_DAILY_ITEMS,
    _append_translation_for_english_content,
    _contains_required_marker,
    _filter_items_for_window,
    _generate_my_news_with_marker_guard,
    _get_report_window,
    _parse_args,
)


def test_filter_items_for_window_only_keeps_items_inside_range():
    start_utc = datetime(2026, 3, 14, 0, 0, tzinfo=timezone.utc)
    end_utc = datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)
    items = [
        {"title": "in-range", "published_at": "2026-03-14T12:00:00Z"},
        {"title": "start-boundary", "published_at": "2026-03-14T00:00:00Z"},
        {"title": "end-boundary", "published_at": "2026-03-15T00:00:00Z"},
        {"title": "unknown", "published": ""},
    ]

    filtered = _filter_items_for_window(items, start_utc, end_utc)

    assert [item["title"] for item in filtered] == ["in-range", "start-boundary"]


def test_daily_total_limit_is_10_items():
    start_utc = datetime(2026, 3, 14, 0, 0, tzinfo=timezone.utc)
    end_utc = datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)
    articles = [
        {"id": i, "published_at": f"2026-03-14T12:{i:02d}:00Z"} for i in range(12)
    ]
    tweets = [{"id": i, "published_at": f"2026-03-14T13:{i:02d}:00Z"} for i in range(5)]

    filtered_articles = _filter_items_for_window(articles, start_utc, end_utc)
    filtered_tweets = _filter_items_for_window(tweets, start_utc, end_utc)

    limited_articles = filtered_articles[:_MAX_DAILY_ITEMS]
    limited_tweets = filtered_tweets[: max(0, _MAX_DAILY_ITEMS - len(limited_articles))]

    assert len(limited_articles) + len(limited_tweets) == 10
    assert len(limited_articles) == 10
    assert len(limited_tweets) == 0


def test_report_window_defaults_to_yesterday_8_to_today_8_for_utc8():
    now_utc = datetime(2026, 3, 15, 2, 30, tzinfo=timezone.utc)  # UTC+8 = 10:30
    start_utc, end_utc = _get_report_window(now_utc, 8, 8)

    assert start_utc == datetime(2026, 3, 14, 0, 0, tzinfo=timezone.utc)
    assert end_utc == datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)


def test_report_window_supports_rolling_mode_last_24_hours():
    now_utc = datetime(2026, 3, 15, 2, 30, tzinfo=timezone.utc)
    start_utc, end_utc = _get_report_window(now_utc, 8, 8, mode="rolling")

    assert start_utc == datetime(2026, 3, 14, 2, 30, tzinfo=timezone.utc)
    assert end_utc == now_utc


def test_report_window_unknown_mode_falls_back_to_anchored():
    now_utc = datetime(2026, 3, 15, 2, 30, tzinfo=timezone.utc)  # UTC+8 = 10:30
    start_utc, end_utc = _get_report_window(now_utc, 8, 8, mode="invalid")

    assert start_utc == datetime(2026, 3, 14, 0, 0, tzinfo=timezone.utc)
    assert end_utc == datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)


def test_append_translation_for_english_content(monkeypatch):
    monkeypatch.setattr("src.translator.is_english_only", lambda text: text.startswith("Hello world"))
    monkeypatch.setattr(
        "src.translator.translate_to_chinese",
        lambda text: "" if text == "Hello world (fail)" else "你好，世界",
    )

    items = [
        {"summary": "Hello world"},
        {"summary": "你好世界"},
        {"summary": "", "title": "Hello world"},
        {"summary": "Hello world (fail)"},
    ]
    enriched = _append_translation_for_english_content(
        items, "summary", fallback_text_key="title"
    )

    assert enriched[0]["translation"] == "你好，世界"
    assert "translation" not in enriched[1]
    assert enriched[2]["translation"] == "你好，世界"
    assert enriched[3]["translation"] == "（翻译服务暂时不可用）"


def test_parse_args_defaults_to_email_mode(monkeypatch):
    monkeypatch.setattr("sys.argv", ["main.py"])
    args = _parse_args()
    assert args.mode == "email"


def test_parse_args_accepts_my_news_mode(monkeypatch):
    monkeypatch.setattr("sys.argv", ["main.py", "--mode", "my-news"])
    args = _parse_args()
    assert args.mode == "my-news"
    assert args.my_news_action == "full"


def test_parse_args_accepts_my_news_send_action(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "main.py",
            "--mode",
            "my-news",
            "--my-news-action",
            "send",
            "--my-news-file",
            "daily-news/202603230800_daily_news.md",
        ],
    )
    args = _parse_args()
    assert args.mode == "my-news"
    assert args.my_news_action == "send"
    assert args.my_news_file == "daily-news/202603230800_daily_news.md"


def test_contains_required_marker():
    assert _contains_required_marker("abc - 导读 - xyz", "- 导读 -") is True
    assert _contains_required_marker("abc", "- 导读 -") is False


def test_my_news_marker_guard_retries_after_timeout_then_succeeds(monkeypatch, tmp_path):
    calls = {"prepare": 0, "generate": 0, "retry_build": 0, "finalize": 0, "alerts": 0}

    class FakeContext:
        def __init__(self):
            self.messages = [{"role": "user", "content": "seed"}]
            self.allowed_urls = {"https://example.com/a"}
            self.now_utc = datetime(2026, 3, 23, tzinfo=timezone.utc)
            self.bjt_now = self.now_utc

    def fake_prepare(base_dir):
        calls["prepare"] += 1
        return FakeContext()

    def fake_generate_candidate(context):
        calls["generate"] += 1
        if calls["generate"] == 1:
            return "# 标题\n\n无导读"
        return "# 标题\n\n<div><h3>- 导读 -</h3></div>"

    def fake_build_retry(context, markdown, marker):
        calls["retry_build"] += 1
        context.messages = context.messages + [{"role": "assistant", "content": markdown}]

    def fake_finalize(base_dir, markdown, context):
        calls["finalize"] += 1
        return tmp_path / "b.md", markdown

    def fake_alert(subject, html):
        calls["alerts"] += 1

    ticks = iter([0.0, 0.0, 11.0])

    monkeypatch.setattr("main._prepare_my_news_generation_context", fake_prepare)
    monkeypatch.setattr("main._generate_my_news_candidate", fake_generate_candidate)
    monkeypatch.setattr("main._build_my_news_retry_messages", fake_build_retry)
    monkeypatch.setattr("main._finalize_my_news_markdown", fake_finalize)
    monkeypatch.setattr("main._notify_my_news_developer_alert", fake_alert)

    output_file, markdown = _generate_my_news_with_marker_guard(
        tmp_path,
        marker="- 导读 -",
        max_wait_seconds=10,
        retry_interval_seconds=2,
        monotonic_fn=lambda: next(ticks),
        sleep_fn=lambda s: None,
    )

    assert calls["prepare"] == 1
    assert calls["generate"] == 2
    assert calls["retry_build"] == 1
    assert calls["finalize"] == 1
    assert calls["alerts"] == 1
    assert output_file.name == "b.md"
    assert "- 导读 -" in markdown


