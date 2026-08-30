import math
import re
import logging
import pandas as pd
from datetime import date
from app.services.market_data.yfinance_client import get_options_chain

logger = logging.getLogger(__name__)

_OCC_RE = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")


def to_occ_symbol(ticker: str, expiry: str, option_type: str, strike: float) -> str:
    """
    Build the OCC/Alpaca-style contract symbol, e.g. AAPL250926C00230000.
    expiry is 'YYYY-MM-DD'; strike is dollars (converted to the 1/1000ths format).
    """
    exp = expiry.replace("-", "")[2:]              # YYYY-MM-DD -> YYMMDD
    cp = "C" if option_type == "call" else "P"
    strike_int = round(strike * 1000)
    return f"{ticker.upper()}{exp}{cp}{strike_int:08d}"


def parse_occ_symbol(symbol: str) -> dict | None:
    """Parse an OCC-style contract symbol back into its components, or None if not one."""
    m = _OCC_RE.match(symbol.upper())
    if not m:
        return None
    root, exp, cp, strike = m.groups()
    return {
        "ticker": root,
        "expiry": f"20{exp[0:2]}-{exp[2:4]}-{exp[4:6]}",
        "option_type": "call" if cp == "C" else "put",
        "strike": int(strike) / 1000.0,
    }


def contract_size(equity: float, premium: float, risk_pct: float, max_notional_pct: float) -> int:
    """
    Size options contracts off the *premium at risk*, not the underlying's price.
    Each contract = 100 shares, so notional = premium * 100 per contract.

    Unlike equities, a single contract has a real, non-trivial cost — so unlike
    fixed_fraction_size's floor of "at least 1 share", this returns 0 (skip the
    trade) when even one contract would exceed the position-size cap, rather
    than forcing an oversized order through.
    """
    if premium <= 0 or equity <= 0:
        return 0
    cost_per_contract = premium * 100
    max_notional = equity * max_notional_pct
    if cost_per_contract > max_notional:
        return 0
    risk_amount = equity * risk_pct
    contracts = max(1, int(risk_amount / cost_per_contract))
    capped = int(max_notional / cost_per_contract)
    return max(0, min(contracts, capped))


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
