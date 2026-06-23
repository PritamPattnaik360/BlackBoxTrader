import re
import logging
from app.config import settings

logger = logging.getLogger(__name__)
SUBREDDITS = ["stocks", "investing", "wallstreetbets", "options"]
TICKER_PATTERN = re.compile(r"\$([A-Z]{1,5})\b")


def fetch_reddit_mentions(ticker: str) -> list[dict]:
    if not settings.reddit_client_id or not settings.reddit_client_secret:
        return []
    try:
        import praw
        reddit = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        )
        results = []
        for sub_name in SUBREDDITS:
            try:
                sub = reddit.subreddit(sub_name)
                for post in sub.search(f"${ticker}", limit=10, time_filter="day"):
                    if post.upvote_ratio < 0.5:
                        continue
                    text = f"{post.title} {post.selftext[:200]}"
                    results.append({
                        "title": post.title,
                        "source": f"r/{sub_name}",
                        "published_at": str(post.created_utc),
                        "ticker": ticker,
                        "upvote_ratio": post.upvote_ratio,
                        "score": post.score,
                        "text": text,
                    })
            except Exception as e:
                logger.debug(f"Reddit r/{sub_name} error: {e}")
        return results
    except Exception as e:
        logger.warning(f"Reddit fetch error for {ticker}: {e}")
        return []
