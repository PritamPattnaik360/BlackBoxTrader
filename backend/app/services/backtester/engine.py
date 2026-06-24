import pandas as pd
import numpy as np
import logging
from app.services.backtester.data_loader import load_ohlcv, load_intraday_ohlcv
from app.services.backtester.strategy import NLPProxyStrategy, TechnicalStrategy, IntradayORBVWAPStrategy, BaseStrategy
from app.services.backtester.metrics import compute_metrics

logger = logging.getLogger(__name__)

STRATEGIES = {
    "nlp_proxy":    NLPProxyStrategy,
    "sma_crossover": TechnicalStrategy,
    "intraday_orb": IntradayORBVWAPStrategy,
}


def run_backtest(
    tickers: list[str],
    start: str,
    end: str,
    initial_capital: float = 100_000.0,
    strategy_name: str = "nlp_proxy",
    params: dict | None = None,
) -> dict:
    if strategy_name == "intraday_orb":
        return run_intraday_backtest(tickers, start, end, initial_capital, params)

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
            "entry_ts":    str(row.get("entry_ts", "")),
            "exit_ts":     str(row.get("exit_ts", "")),
            "entry_price": round(float(row.get("entry", 0)), 2),
            "exit_price":  round(float(row.get("exit", 0)), 2),
            "qty":         int(row.get("qty", 0)),
            "pnl":         round(float(row.get("pnl", 0)), 2),
            "side":        str(row.get("side", "long")),
            "exit_reason": str(row.get("exit_reason", "")),
        })
    return result


def run_intraday_backtest(
    tickers: list[str],
    start: str,
    end: str,
    initial_capital: float = 100_000.0,
    params: dict | None = None,
) -> dict:
    """
    Replay the VWAP + Opening Range Breakout strategy on 5-minute historical bars.
    yfinance provides up to 60 days of free 5-minute data.

    Each day is simulated independently (no overnight positions).
    The equity curve is built day-by-day from daily P&L.
    """
    params   = params or {}
    strategy = IntradayORBVWAPStrategy(
        orb_minutes  = int(params.get("orb_minutes",  30)),
        stop_pct     = float(params.get("stop_pct",   0.005)),
        allow_short  = bool(params.get("allow_short", False)),
    )

    all_trades: list[dict] = []
    daily_pnl: dict[str, float] = {}  # date → net P&L across all tickers

    for ticker in tickers:
        try:
            df = load_intraday_ohlcv(ticker, start, end)
            if df.empty:
                logger.warning(f"No intraday data for {ticker}")
                continue

            # Group by trading date and simulate each day
            for day, day_df in df.groupby(df.index.date):
                day_str = str(day)
                day_trades = strategy.simulate_day(day_df)
                for t in day_trades:
                    t["ticker"] = ticker
                    all_trades.append(t)
                    daily_pnl[day_str] = daily_pnl.get(day_str, 0.0) + t["pnl"]

        except Exception as e:
            logger.error(f"Intraday backtest error for {ticker}: {e}")

    if not daily_pnl:
        return {"error": "No intraday data available. yfinance only provides 60 days of 5-minute bars."}

    # Build equity curve from daily P&L
    dates  = sorted(daily_pnl.keys())
    equity = initial_capital
    eq_points = []
    for d in dates:
        equity += daily_pnl[d]
        eq_points.append({"ts": d, "value": round(equity, 2)})

    trades_df = pd.DataFrame(all_trades) if all_trades else pd.DataFrame()
    eq_series = pd.Series(
        [p["value"] for p in eq_points],
        index=pd.to_datetime([p["ts"] for p in eq_points]),
    )
    metrics = compute_metrics(eq_series, trades_df if not trades_df.empty else None)
    metrics["equity_curve"] = eq_points

    # Enrich trade log with exit_reason
    trade_log = []
    for t in all_trades:
        trade_log.append({
            "entry_ts":    str(t.get("entry_ts", "")),
            "exit_ts":     str(t.get("exit_ts", "")),
            "ticker":      t.get("ticker", ""),
            "side":        t.get("side", "long"),
            "entry_price": round(float(t.get("entry", 0)), 2),
            "exit_price":  round(float(t.get("exit", 0)), 2),
            "qty":         int(t.get("qty", 0)),
            "pnl":         round(float(t.get("pnl", 0)), 2),
            "exit_reason": t.get("exit_reason", ""),
        })
    metrics["trade_log"] = trade_log

    # Summary breakdown
    if trade_log:
        exits = pd.DataFrame(trade_log)
        metrics["exit_reason_summary"] = exits.groupby("exit_reason")["pnl"].agg(
            count="count", total_pnl="sum", avg_pnl="mean"
        ).round(2).to_dict("index")

    return metrics
