import math
import logging
import pandas as pd
from datetime import date
from app.services.market_data.yfinance_client import get_options_chain

logger = logging.getLogger(__name__)


def black_scholes_greeks(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call") -> dict:
    """T = years to expiry, r = risk-free rate, sigma = IV"""
    if T <= 0 or sigma <= 0:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "price": 0}
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    def N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
    def n(x): return math.exp(-0.5 * x**2) / math.sqrt(2 * math.pi)

    if option_type == "call":
        price = S * N(d1) - K * math.exp(-r * T) * N(d2)
        delta = N(d1)
    else:
        price = K * math.exp(-r * T) * N(-d2) - S * N(-d1)
        delta = N(d1) - 1

    gamma = n(d1) / (S * sigma * math.sqrt(T))
    vega = S * n(d1) * math.sqrt(T) / 100
    if option_type == "call":
        theta = (-S * n(d1) * sigma / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * N(d2)) / 365
    else:
        theta = (-S * n(d1) * sigma / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * N(-d2)) / 365

    return {
        "price": round(price, 4),
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 6),
        "vega": round(vega, 4),
    }


def select_best_strike(ticker: str, current_price: float, direction: str, target_dte: int = 30) -> dict | None:
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        dates = t.options
        if not dates:
            return None

        # Find expiry closest to target_dte
        today = date.today()
        best_expiry = min(dates, key=lambda d: abs((date.fromisoformat(d) - today).days - target_dte))
        calls, puts = get_options_chain(ticker, best_expiry)
        chain = calls if direction == "BUY" else puts
        if chain.empty:
            return None

        # Near ATM strike
        chain = chain.copy()
        chain["moneyness"] = (chain["strike"] - current_price).abs()
        best = chain.nsmallest(1, "moneyness").iloc[0]

        dte = (date.fromisoformat(best_expiry) - today).days
        T = dte / 365
        sigma = float(best.get("impliedVolatility", 0.3) or 0.3)
        greeks = black_scholes_greeks(current_price, float(best["strike"]), T, 0.05, sigma,
                                       "call" if direction == "BUY" else "put")
        return {
            "ticker": ticker,
            "expiry": best_expiry,
            "strike": float(best["strike"]),
            "option_type": "call" if direction == "BUY" else "put",
            "dte": dte,
            "iv": round(sigma, 4),
            "bid": float(best.get("bid", 0)),
            "ask": float(best.get("ask", 0)),
            **greeks,
        }
    except Exception as e:
        logger.warning(f"Options selection failed for {ticker}: {e}")
        return None
