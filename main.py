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
import time as time_module
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable

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
    mode: str = "anchored",
) -> tuple[datetime, datetime]:
    """Return report window bounds in UTC: [start, end)."""
    normalized_mode = (mode or "anchored").strip().lower()
    if normalized_mode == "rolling":
        return now_utc - timedelta(days=1), now_utc

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
        "--my-news-action",
        choices=["full", "generate", "send"],
        default="full",
        help=(
            "Only for --mode my-news: 'full' (generate+send, default), "
            "'generate' (generate only), 'send' (send existing markdown only)."
        ),
    )
    parser.add_argument(
        "--my-news-file",
        metavar="FILE",
        help=(
            "Only for --mode my-news --my-news-action send: "
            "send this markdown file instead of auto-selecting today's generated file."
        ),
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


def _contains_required_marker(markdown: str, marker: str) -> bool:
    return marker.strip() in (markdown or "")


def _generate_my_news_once(base_dir: Path) -> tuple[Path, str]:
    from src.my_news_generator import generate_my_news_markdown

    return generate_my_news_markdown(base_dir)


def _prepare_my_news_generation_context(base_dir: Path):
    from src.my_news_generator import prepare_my_news_generation_context

    return prepare_my_news_generation_context(base_dir)


def _generate_my_news_candidate(context) -> str:
    from src.my_news_generator import generate_my_news_candidate_markdown

    markdown, _ = generate_my_news_candidate_markdown(
        context.messages,
        context.bjt_now,
    )
    return markdown


def _build_my_news_retry_messages(context, failed_markdown: str, marker: str) -> None:
    from src.my_news_generator import build_my_news_retry_messages

    context.messages = build_my_news_retry_messages(
        context.messages,
        failed_markdown,
        marker,
    )


def _finalize_my_news_markdown(base_dir: Path, markdown: str, context) -> tuple[Path, str]:
    from src.my_news_generator import finalize_my_news_markdown

    return finalize_my_news_markdown(
        base_dir,
        markdown,
        context.allowed_urls,
        now_utc=context.now_utc,
        bjt_now=context.bjt_now,
    )


def _notify_my_news_developer_alert(subject: str, html_body: str) -> None:
    from src.config import DEVELOPER_ALERT_RECIPIENTS

    if not DEVELOPER_ALERT_RECIPIENTS:
        logger.warning(
            "DEVELOPER_ALERT_RECIPIENTS is empty. Skip my-news developer alert email."
        )
        return

    from src.email_sender import send_email

    send_email(subject, html_body, recipients=DEVELOPER_ALERT_RECIPIENTS)


def _generate_my_news_with_marker_guard(
    base_dir: Path,
    marker: str,
    max_wait_seconds: int,
    retry_interval_seconds: int,
    monotonic_fn: Callable[[], float] = time_module.monotonic,
    sleep_fn: Callable[[float], None] = time_module.sleep,
) -> tuple[Path, str]:
    context = _prepare_my_news_generation_context(base_dir)
    started = monotonic_fn()
    last_output_file: Path | None = None
    last_markdown = ""
    attempt = 0

    while monotonic_fn() - started < max_wait_seconds:
        attempt += 1
        markdown = _generate_my_news_candidate(context)
        last_markdown = markdown
        if _contains_required_marker(markdown, marker):
            output_file, finalized_markdown = _finalize_my_news_markdown(
                base_dir,
                markdown,
                context,
            )
            return output_file, finalized_markdown

        elapsed = monotonic_fn() - started
        remaining = max(0, max_wait_seconds - int(elapsed))
        logger.warning(
            "my-news attempt %d missing required marker '%s'; waiting and retrying (%ds left).",
            attempt,
            marker,
            remaining,
        )
        if remaining <= 0:
            break
        _build_my_news_retry_messages(context, markdown, marker)
        sleep_seconds = min(retry_interval_seconds, remaining)
        if sleep_seconds > 0:
            sleep_fn(float(sleep_seconds))

    # Timeout reached: notify developers and do one final retry as requested.
    alert_subject = "[AI-Daily告警] my-news 导读标记缺失，已触发超时重试"
    alert_html = (
        "<html><body>"
        f"<p>my-news 在 {max_wait_seconds} 秒内未检测到必须标记：<strong>{marker}</strong></p>"
        "<p>系统将执行一次最终重试。请检查模型配置与提示词。</p>"
        "</body></html>"
    )
    try:
        _notify_my_news_developer_alert(alert_subject, alert_html)
    except Exception as exc:
        logger.warning("Failed to send my-news developer alert: %s", exc)

    if last_markdown:
        _build_my_news_retry_messages(context, last_markdown, marker)
    markdown = _generate_my_news_candidate(context)
    if _contains_required_marker(markdown, marker):
        output_file, finalized_markdown = _finalize_my_news_markdown(
            base_dir,
            markdown,
            context,
        )
        return output_file, finalized_markdown

    raise RuntimeError(
        "my-news output does not contain required marker "
        f"'{marker}' after timeout and final retry. No final file was saved."
    )


def main() -> None:
    args = _parse_args()
    now_utc = datetime.now(timezone.utc)

    if args.mode == "my-news":
        from src.config import (
            MY_NEWS_MAX_WAIT_SECONDS,
            MY_NEWS_REQUIRED_MARKER,
            MY_NEWS_RETRY_INTERVAL_SECONDS,
        )
        from src.my_news_generator import (
            load_my_news_markdown_for_sending,
            render_my_news_email,
        )

        base_dir = Path(__file__).parent
        action = args.my_news_action

        if action == "send" and args.my_news_file:
            preferred_file = Path(args.my_news_file)
        else:
            preferred_file = None

        if action in ("full", "generate"):
            output_file, markdown = _generate_my_news_with_marker_guard(
                base_dir,
                marker=MY_NEWS_REQUIRED_MARKER,
                max_wait_seconds=MY_NEWS_MAX_WAIT_SECONDS,
                retry_interval_seconds=MY_NEWS_RETRY_INTERVAL_SECONDS,
            )
            logger.info("my-news markdown saved to %s", output_file.resolve())
            print(f"日报已生成并保存：{output_file}")
            if action == "generate":
                if args.output:
                    _, html_body, _ = render_my_news_email(
                        markdown,
                        base_dir,
                        use_cid_images=False,
                    )
                    out = Path(args.output)
                    out.write_text(html_body, encoding="utf-8")
                    logger.info("my-news HTML saved to %s", out.resolve())
                elif args.dry_run:
                    _, html_body, _ = render_my_news_email(
                        markdown,
                        base_dir,
                        use_cid_images=False,
                    )
                    print(html_body)
                return
        else:
            output_file, markdown = load_my_news_markdown_for_sending(
                base_dir,
                now_utc=now_utc,
                preferred_file=preferred_file,
            )
            logger.info("Using existing my-news markdown: %s", output_file.resolve())
            print(f"将发送已生成日报：{output_file}")

        if args.output:
            _, html_body, _ = render_my_news_email(
                markdown,
                base_dir,
                use_cid_images=False,
            )
            out = Path(args.output)
            out.write_text(html_body, encoding="utf-8")
            logger.info("my-news HTML saved to %s", out.resolve())
            return

        subject, html_body, inline_images = render_my_news_email(
            markdown,
            base_dir,
            use_cid_images=True,
        )

        if args.dry_run:
            print(html_body)
            return

        logger.info("── my-news: Sending email …")
        from src.email_sender import send_email

        send_email(subject, html_body, inline_images=inline_images)
        logger.info("my-news sent. ✓")
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
        REPORT_WINDOW_MODE,
        REPORT_WINDOW_HOUR,
        REPORT_WINDOW_TZ_OFFSET,
    )

    window_start_utc, window_end_utc = _get_report_window(
        now_utc,
        REPORT_WINDOW_HOUR,
        REPORT_WINDOW_TZ_OFFSET,
        REPORT_WINDOW_MODE,
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
