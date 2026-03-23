"""
main.py  –  Orchestrate the AI Daily newsletter pipeline.

Usage::

    python main.py              # fetch, render, and send
    python main.py --dry-run    # fetch and render, print HTML to stdout (no send)
    python main.py --output report.html   # save rendered HTML to a file
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

# Configure logging before any local imports
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
_MAX_DAILY_ITEMS = 10


def _parse_item_published_datetime(item: dict) -> datetime | None:
    """Parse item publication time as an aware UTC datetime."""
    published_at = (item.get("published_at") or "").strip()
    if published_at:
        try:
            dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            return (
                dt.astimezone(timezone.utc)
                if dt.tzinfo
                else dt.replace(tzinfo=timezone.utc)
            )
        except Exception:
            pass

    published = (item.get("published") or "").strip()
    if not published:
        return None
    try:
        day = date.fromisoformat(published)
        return datetime.combine(day, time.min, tzinfo=timezone.utc)
    except ValueError:
        return None


def _get_report_window(
    now_utc: datetime,
    anchor_hour: int,
    tz_offset_hours: int,
) -> tuple[datetime, datetime]:
    """Return report window bounds in UTC: [start, end)."""
    tz = timezone(timedelta(hours=tz_offset_hours))
    local_now = now_utc.astimezone(tz)
    end_local = local_now.replace(
        hour=anchor_hour, minute=0, second=0, microsecond=0
    )
    if local_now < end_local:
        end_local -= timedelta(days=1)
    start_local = end_local - timedelta(days=1)
    return (
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
    )


def _filter_items_for_window(
    items: list[dict],
    start_utc: datetime,
    end_utc: datetime,
) -> list[dict]:
    """Keep only items published within [start_utc, end_utc)."""
    filtered: list[dict] = []
    for item in items:
        published_dt = _parse_item_published_datetime(item)
        if published_dt is not None and start_utc <= published_dt < end_utc:
            filtered.append(item)
    return filtered


def _append_translation_for_english_content(
    items: list[dict],
    text_key: str,
    fallback_text_key: str | None = None,
) -> list[dict]:
    """Add a Chinese translation line for English-only content."""
    from src.translator import is_english_only, translate_to_chinese

    enriched: list[dict] = []
    for item in items:
        new_item = dict(item)
        text = (new_item.get(text_key) or "").strip()
        if not text and fallback_text_key:
            text = (new_item.get(fallback_text_key) or "").strip()
        if is_english_only(text):
            translation = translate_to_chinese(text) or "（翻译服务暂时不可用）"
            new_item["translation"] = translation
        enriched.append(new_item)
    return enriched


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and send the daily AI newsletter."
    )
    parser.add_argument(
        "--mode",
        choices=["email", "my-news"],
        default="email",
        help="Output mode: 'email' (default) or 'my-news' markdown via DeepSeek.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render the email and print it to stdout without sending.",
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Save the rendered HTML to FILE instead of sending.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    now_utc = datetime.now(timezone.utc)

    if args.mode == "my-news":
        from src.my_news_generator import generate_my_news_markdown

        output_file, _ = generate_my_news_markdown(Path(__file__).parent)
        logger.info("my-news markdown saved to %s", output_file.resolve())
        print(f"日报已生成并保存：{output_file}")
        return

    # ── 1. Fetch content ────────────────────────────────────────────────
    logger.info("── Step 1/3: Fetching news from RSS feeds …")
    from src.fetchers.news_fetcher import fetch_all_news

    articles = fetch_all_news()
    logger.info("Total articles fetched: %d", len(articles))

    logger.info("── Step 2/3: Fetching tweets from AI influencers …")
    from src.fetchers.twitter_fetcher import fetch_all_tweets

    tweets = fetch_all_tweets()
    logger.info("Total tweets fetched: %d", len(tweets))

    from src.config import (
        ENABLE_ENGLISH_TRANSLATION,
        REPORT_WINDOW_HOUR,
        REPORT_WINDOW_TZ_OFFSET,
    )

    window_start_utc, window_end_utc = _get_report_window(
        now_utc, REPORT_WINDOW_HOUR, REPORT_WINDOW_TZ_OFFSET
    )
    articles = _filter_items_for_window(articles, window_start_utc, window_end_utc)
    tweets = _filter_items_for_window(tweets, window_start_utc, window_end_utc)
    articles = articles[:_MAX_DAILY_ITEMS]
    tweets = tweets[: max(0, _MAX_DAILY_ITEMS - len(articles))]
    if ENABLE_ENGLISH_TRANSLATION:
        articles = _append_translation_for_english_content(
            articles, "summary", fallback_text_key="title"
        )
        tweets = _append_translation_for_english_content(tweets, "text")
    logger.info(
        "Keeping content in window [%s, %s): %d article(s), %d tweet(s), total=%d (max=%d)",
        window_start_utc.isoformat(),
        window_end_utc.isoformat(),
        len(articles),
        len(tweets),
        len(articles) + len(tweets),
        _MAX_DAILY_ITEMS,
    )

    if not articles and not tweets:
        logger.error("No content fetched – aborting.")
        sys.exit(1)

    # ── 2. Render email ─────────────────────────────────────────────────
    from src.composer import render_email

    subject, html_body = render_email(articles, tweets)
    logger.info("Email rendered: '%s'", subject)

    # ── 3. Deliver ──────────────────────────────────────────────────────
    if args.output:
        out = Path(args.output)
        out.write_text(html_body, encoding="utf-8")
        logger.info("HTML saved to %s", out.resolve())
        return

    if args.dry_run:
        print(html_body)
        return

    logger.info("── Step 3/3: Sending email …")
    from src.email_sender import send_email

    send_email(subject, html_body)
    logger.info("Done. ✓")


if __name__ == "__main__":
    main()
