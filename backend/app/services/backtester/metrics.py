import numpy as np
import pandas as pd


def compute_metrics(equity_curve: pd.Series, trade_log: pd.DataFrame | None = None) -> dict:
    if equity_curve.empty or len(equity_curve) < 2:
        return {}

    returns = equity_curve.pct_change().dropna()
    total_return = (equity_curve.iloc[-1] / equity_curve.iloc[0]) - 1
    n_years = len(equity_curve) / 252
    cagr = (1 + total_return) ** (1 / max(n_years, 0.01)) - 1

    sharpe = float(returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0.0

    negative = returns[returns < 0]
    sortino = float(returns.mean() / negative.std() * np.sqrt(252)) if len(negative) > 1 and negative.std() > 0 else 0.0

    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    max_dd = float(drawdown.min())
    calmar = float(cagr / abs(max_dd)) if max_dd != 0 else 0.0

    win_rate, profit_factor, total_trades = None, None, None
    if trade_log is not None and not trade_log.empty and "pnl" in trade_log.columns:
        total_trades = len(trade_log)
        wins = trade_log[trade_log["pnl"] > 0]
        losses = trade_log[trade_log["pnl"] <= 0]
        win_rate = len(wins) / total_trades if total_trades > 0 else 0.0
        gross_profit = wins["pnl"].sum()
        gross_loss = abs(losses["pnl"].sum())
        profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    equity_points = _downsample(equity_curve, 500)

    return {
        "total_return": round(total_return, 4),
        "cagr": round(cagr, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "max_drawdown": round(max_dd, 4),
        "calmar": round(calmar, 4),
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "total_trades": total_trades,
        "equity_curve": equity_points,
    }


def _downsample(series: pd.Series, n: int) -> list[dict]:
    if len(series) > n:
        idx = np.linspace(0, len(series) - 1, n, dtype=int)
        series = series.iloc[idx]
    return [{"ts": str(ts), "value": round(float(v), 2)} for ts, v in series.items()]
