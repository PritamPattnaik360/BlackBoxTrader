from fastapi import APIRouter, HTTPException
from app.services.market_data.yfinance_client import get_snapshot, get_options_chain
from app.services.market_data.cache import get_quote, set_quote

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/quote/{ticker}")
async def get_quote_endpoint(ticker: str):
    ticker = ticker.upper()
    cached = get_quote(ticker)
    if cached:
        return cached
    try:
        data = get_snapshot(ticker)
        set_quote(ticker, data)
        return data
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/chain/{ticker}")
async def get_options_chain_endpoint(ticker: str, expiry: str | None = None):
    ticker = ticker.upper()
    try:
        calls, puts = get_options_chain(ticker, expiry)
        return {
            "ticker": ticker,
            "calls": calls.head(20).to_dict(orient="records") if not calls.empty else [],
            "puts": puts.head(20).to_dict(orient="records") if not puts.empty else [],
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
