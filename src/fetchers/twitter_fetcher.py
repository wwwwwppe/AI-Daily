"""
src/fetchers/twitter_fetcher.py  –  Fetch recent tweets from AI influencers via
                                     the Twitter / X API v2.

Each tweet is returned as a dict::

    {
        "author":       str,   # display name
        "username":     str,   # @handle (without @)
        "text":         str,   # tweet text
        "url":          str,   # permalink to the tweet
        "published":    str,   # ISO-8601 date string
    }

When TWITTER_BEARER_TOKEN is absent the module returns an empty list and logs a
warning instead of raising an exception – this allows the daily report to run
with RSS-only content.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from src.config import (
    HTTP_PROXY,
    HTTPS_PROXY,
    REQUEST_TIMEOUT,
    TWITTER_ACCOUNTS,
    TWITTER_BEARER_TOKEN,
)

logger = logging.getLogger(__name__)

_API_BASE = "https://api.twitter.com/2"

_PROXIES: dict | None = (
    {"http": HTTP_PROXY, "https": HTTPS_PROXY}
    if HTTP_PROXY or HTTPS_PROXY
    else None
)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _session() -> requests.Session:
    sess = requests.Session()
    sess.headers["Authorization"] = f"Bearer {TWITTER_BEARER_TOKEN}"
    if _PROXIES:
        sess.proxies.update(_PROXIES)
    return sess


def _get_user_id(session: requests.Session, username: str) -> str | None:
    """Resolve a Twitter username to its numeric user ID."""
    url = f"{_API_BASE}/users/by/username/{username}"
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("id")
    except Exception as exc:
        logger.warning("Could not resolve user ID for @%s: %s", username, exc)
        return None


def _fetch_user_tweets(
    session: requests.Session,
    username: str,
    user_id: str,
    max_results: int,
) -> list[dict]:
    """Return recent tweets for a user."""
    url = f"{_API_BASE}/users/{user_id}/tweets"
    params = {
        "max_results": max(5, min(max_results, 100)),
        "tweet.fields": "created_at,text,author_id",
        "expansions": "author_id",
        "user.fields": "name,username",
        "exclude": "retweets,replies",
    }
    tweets: list[dict] = []
    try:
        resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()

        # Build a map from user_id → display name
        users_map: dict[str, str] = {}
        for u in body.get("includes", {}).get("users", []):
            users_map[u["id"]] = u.get("name", u.get("username", username))

        for tweet in body.get("data", [])[:max_results]:
            tweet_id = tweet.get("id", "")
            text = tweet.get("text", "")
            author_id = tweet.get("author_id", "")
            display_name = users_map.get(author_id, username)
            created_at = tweet.get("created_at", "")

            # Convert ISO timestamp to YYYY-MM-DD
            published = ""
            published_at = ""
            if created_at:
                try:
                    dt = datetime.fromisoformat(
                        created_at.replace("Z", "+00:00")
                    )
                    published = dt.strftime("%Y-%m-%d")
                    published_at = dt.astimezone(timezone.utc).isoformat().replace(
                        "+00:00", "Z"
                    )
                except Exception:
                    published = created_at[:10]
                    published_at = created_at

            tweet_url = f"https://twitter.com/{username}/status/{tweet_id}"
            tweets.append(
                {
                    "author": display_name,
                    "username": username,
                    "text": text,
                    "url": tweet_url,
                    "published": published,
                    "published_at": published_at,
                }
            )
    except Exception as exc:
        logger.warning(
            "Failed to fetch tweets for @%s: %s", username, exc
        )
    return tweets


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_all_tweets() -> list[dict]:
    """
    Fetch recent tweets from all configured AI influencer accounts.

    Returns an empty list (with a logged warning) when TWITTER_BEARER_TOKEN is
    not configured – the daily report will still run with news-only content.
    """
    if not TWITTER_BEARER_TOKEN:
        logger.warning(
            "TWITTER_BEARER_TOKEN is not set. "
            "Skipping Twitter content – set the token to include influencer tweets."
        )
        return []

    session = _session()
    all_tweets: list[dict] = []

    for account in TWITTER_ACCOUNTS:
        username: str = account.get("username", "")
        max_tweets: int = int(account.get("max_tweets", 3))

        if not username:
            continue

        user_id = _get_user_id(session, username)
        if not user_id:
            continue

        tweets = _fetch_user_tweets(session, username, user_id, max_tweets)
        logger.info(
            "Fetched %d tweet(s) from @%s", len(tweets), username
        )
        all_tweets.extend(tweets)

    return all_tweets
