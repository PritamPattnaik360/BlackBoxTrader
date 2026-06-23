import pandas as pd
import numpy as np
import logging
from app.services.backtester.data_loader import load_ohlcv
from app.services.backtester.strategy import NLPProxyStrategy, TechnicalStrategy, BaseStrategy
from app.services.backtester.metrics import compute_metrics

logger = logging.getLogger(__name__)

STRATEGIES = {
    "nlp_proxy": NLPProxyStrategy,
    "sma_crossover": TechnicalStrategy,
}


def run_backtest(
    tickers: list[str],
    start: str,
    end: str,
    initial_capital: float = 100_000.0,
    strategy_name: str = "nlp_proxy",
    params: dict | None = None,
) -> dict:
    params = params or {}
    StratClass = STRATEGIES.get(strategy_name, NLPProxyStrategy)
    strategy: BaseStrategy = StratClass(**{k: v for k, v in params.items() if k in StratClass.__init__.__code__.co_varnames})

    capital_per_ticker = initial_capital / len(tickers)
    all_equity: list[pd.Series] = []
    all_trades: list[pd.DataFrame] = []

    for ticker in tickers:
        try:
            df = load_ohlcv(ticker, start, end)
            if df.empty or len(df) < 50:
                logger.warning(f"Insufficient data for {ticker}")
                continue

            signals = strategy.generate_signals(df)
            equity, trades = _simulate(df, signals, capital_per_ticker)
            all_equity.append(equity)
            all_trades.append(trades)
        except Exception as e:
            logger.error(f"Backtest error for {ticker}: {e}")

    if not all_equity:
        return {"error": "No data available for any ticker"}

    combined_equity = sum(all_equity) if len(all_equity) > 1 else all_equity[0]
    combined_trades = pd.concat(all_trades) if all_trades else pd.DataFrame()
    metrics = compute_metrics(combined_equity, combined_trades)
    trade_log = _trades_to_log(combined_trades)
    return {**metrics, "trade_log": trade_log}


def _simulate(df: pd.DataFrame, signals: pd.Series, capital: float) -> tuple[pd.Series, pd.DataFrame]:
    position = 0
    cash = capital
    equity = pd.Series(index=df.index, dtype=float)
    entry_price = 0.0
    entry_date = None
    trades = []

    for i, (ts, row) in enumerate(df.iterrows()):
        price = float(row["close"])
        sig = signals.iloc[i]

        if position == 0 and sig == 1:
            shares = int(cash * 0.95 / price)
            if shares > 0:
                position = shares
                entry_price = price
                entry_date = ts
                cash -= shares * price

        elif position > 0 and sig == -1:
            cash += position * price
            pnl = (price - entry_price) * position
            trades.append({"entry_ts": entry_date, "exit_ts": ts, "entry": entry_price, "exit": price, "qty": position, "pnl": pnl})
            position = 0
            entry_price = 0.0

        equity.iloc[i] = cash + position * price

    if position > 0:
        cash += position * df["close"].iloc[-1]
        equity.iloc[-1] = cash

    return equity.ffill(), pd.DataFrame(trades)


def _trades_to_log(trades: pd.DataFrame) -> list[dict]:
    if trades.empty:
        return []
    result = []
    for _, row in trades.iterrows():
        result.append({
            "entry_ts": str(row.get("entry_ts", "")),
            "exit_ts": str(row.get("exit_ts", "")),
            "entry_price": round(float(row.get("entry", 0)), 2),
            "exit_price": round(float(row.get("exit", 0)), 2),
            "qty": int(row.get("qty", 0)),
            "pnl": round(float(row.get("pnl", 0)), 2),
        })
    return result
