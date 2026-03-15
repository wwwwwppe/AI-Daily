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
from datetime import date
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


def _filter_items_for_date(items: list[dict], target_date: date) -> list[dict]:
    """Keep only items published on ``target_date``."""
    target_iso = target_date.strftime("%Y-%m-%d")
    return [item for item in items if item.get("published") == target_iso]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and send the daily AI newsletter."
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
    today = date.today()

    # ── 1. Fetch content ────────────────────────────────────────────────
    logger.info("── Step 1/3: Fetching news from RSS feeds …")
    from src.fetchers.news_fetcher import fetch_all_news

    articles = fetch_all_news()
    logger.info("Total articles fetched: %d", len(articles))

    logger.info("── Step 2/3: Fetching tweets from AI influencers …")
    from src.fetchers.twitter_fetcher import fetch_all_tweets

    tweets = fetch_all_tweets()
    logger.info("Total tweets fetched: %d", len(tweets))

    articles = _filter_items_for_date(articles, today)
    tweets = _filter_items_for_date(tweets, today)
    articles = articles[:_MAX_DAILY_ITEMS]
    tweets = tweets[: max(0, _MAX_DAILY_ITEMS - len(articles))]
    logger.info(
        "Keeping today's content only (%s): %d article(s), %d tweet(s), total=%d (max=%d)",
        today.strftime("%Y-%m-%d"),
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
