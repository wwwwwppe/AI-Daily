"""
src/composer.py  –  Render the HTML email from fetched content.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.config import EMAIL_SUBJECT_TEMPLATE


def _get_templates_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "templates"
    else:
        return Path(__file__).parent.parent / "templates"


_TEMPLATES_DIR = _get_templates_dir()
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def render_email(
    articles: list[dict],
    tweets: list[dict],
    report_date: date | None = None,
) -> tuple[str, str]:
    """
    Render the HTML email body and return ``(subject, html_body)``.

    Parameters
    ----------
    articles:
        List of article dicts from ``news_fetcher.fetch_all_news()``.
    tweets:
        List of tweet dicts from ``twitter_fetcher.fetch_all_tweets()``.
    report_date:
        Date to display in the email.  Defaults to *today*.
    """
    if report_date is None:
        report_date = date.today()

    date_str = report_date.strftime("%Y年%m月%d日")
    subject = EMAIL_SUBJECT_TEMPLATE.format(date=date_str)

    template = _env.get_template("email.html")
    html_body = template.render(
        subject=subject,
        date=date_str,
        articles=articles,
        tweets=tweets,
    )
    return subject, html_body
