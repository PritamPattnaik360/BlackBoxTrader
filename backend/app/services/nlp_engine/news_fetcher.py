import httpx
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from app.config import settings

logger = logging.getLogger(__name__)


async def fetch_news(ticker: str) -> list[dict]:
    """Try NewsAPI → GNews → yfinance built-in news (free, no key needed)."""
    articles = []
    articles += await _fetch_newsapi(ticker)
    if not articles:
        articles += await _fetch_gnews(ticker)
    if not articles:
        articles += await _fetch_yfinance_news(ticker)
    return articles


async def _fetch_yfinance_news(ticker: str) -> list[dict]:
    """
    yfinance Ticker.news returns recent articles with no API key.
    Handles both the legacy flat format and the newer nested content format.
    """
    try:
        import yfinance as yf
        t = await asyncio.to_thread(lambda: yf.Ticker(ticker))
        news = await asyncio.to_thread(lambda: t.news)
        if not news:
            return []
        results = []
        for item in news[:20]:
            # New yfinance format: data nested under "content"
            content = item.get("content") or {}
            title = (
                item.get("title")
                or content.get("title")
                or content.get("headline")
                or ""
            )
            if not title:
                continue
            pub_ts = (
                item.get("providerPublishTime")
                or item.get("published_at")
                or content.get("pubDate")
                or content.get("publishedAt")
            )
            source = (
                item.get("publisher")
                or (content.get("provider") or {}).get("displayName")
                or "yfinance"
            )
            # Convert ISO string timestamps to unix float
            if isinstance(pub_ts, str):
                try:
                    pub_ts = datetime.fromisoformat(pub_ts.replace("Z", "+00:00")).timestamp()
                except Exception:
                    pub_ts = None
            results.append({
                "title": title,
                "source": source,
                "published_at": float(pub_ts) if pub_ts else "",
                "ticker": ticker,
            })
        logger.debug(f"yfinance news: {len(results)} articles for {ticker}")
        return results
    except Exception as e:
        logger.warning(f"yfinance news error for {ticker}: {e}")
        return []


async def _fetch_newsapi(ticker: str) -> list[dict]:
    if not settings.newsapi_key:
        return []
    from_date = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": ticker,
        "from": from_date,
        "sortBy": "publishedAt",
        "language": "en",
        "apiKey": settings.newsapi_key,
        "pageSize": 20,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            return [
                {
                    "title": a.get("title", ""),
                    "source": a.get("source", {}).get("name", "newsapi"),
                    "published_at": a.get("publishedAt", ""),
                    "ticker": ticker,
                }
                for a in data.get("articles", [])
                if a.get("title")
            ]
    except Exception as e:
        logger.warning(f"NewsAPI error for {ticker}: {e}")
        return []


async def _fetch_gnews(ticker: str) -> list[dict]:
    if not settings.gnews_api_key:
        return []
    url = "https://gnews.io/api/v4/search"
    params = {
        "q": ticker,
        "lang": "en",
        "max": 10,
        "apikey": settings.gnews_api_key,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            return [
                {
                    "title": a.get("title", ""),
                    "source": a.get("source", {}).get("name", "gnews"),
                    "published_at": a.get("publishedAt", ""),
                    "ticker": ticker,
                }
                for a in data.get("articles", [])
                if a.get("title")
            ]
    except Exception as e:
        logger.warning(f"GNews error for {ticker}: {e}")
        return []
