from __future__ import annotations

from datetime import date

from main import _MAX_DAILY_ITEMS, _filter_items_for_date


def test_filter_items_for_date_only_keeps_target_day():
    target = date(2026, 3, 15)
    items = [
        {"title": "today", "published": "2026-03-15"},
        {"title": "yesterday", "published": "2026-03-14"},
        {"title": "old", "published": "2026-03-13"},
        {"title": "unknown", "published": ""},
    ]

    filtered = _filter_items_for_date(items, target)

    assert [item["title"] for item in filtered] == ["today"]


def test_daily_total_limit_is_10_items():
    today = date(2026, 3, 15).strftime("%Y-%m-%d")
    articles = [{"id": i, "published": today} for i in range(12)]
    tweets = [{"id": i, "published": today} for i in range(5)]

    filtered_articles = _filter_items_for_date(articles, date(2026, 3, 15))
    filtered_tweets = _filter_items_for_date(tweets, date(2026, 3, 15))

    limited_articles = filtered_articles[:_MAX_DAILY_ITEMS]
    limited_tweets = filtered_tweets[: max(0, _MAX_DAILY_ITEMS - len(limited_articles))]

    assert len(limited_articles) + len(limited_tweets) == 10
    assert len(limited_articles) == 10
    assert len(limited_tweets) == 0
