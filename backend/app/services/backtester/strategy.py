import math
import pandas as pd
import numpy as np
from datetime import time as dtime


class BaseStrategy:
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        raise NotImplementedError


class NLPProxyStrategy(BaseStrategy):
    """RSI+MACD crossover as a surrogate for NLP signals in historical backtests."""

    def __init__(self, rsi_period: int = 14, fast: int = 12, slow: int = 26, signal: int = 9):
        self.rsi_period = rsi_period
        self.fast = fast
        self.slow = slow
        self.signal_period = signal

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(self.rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(self.rsi_period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - 100 / (1 + rs)

        # MACD
        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=self.signal_period, adjust=False).mean()
        macd_hist = macd - macd_signal

        # Entry: RSI < 40 (oversold) AND MACD histogram crosses positive
        buy = (rsi < 40) & (macd_hist > 0) & (macd_hist.shift(1) <= 0)
        # Exit: RSI > 65 OR MACD histogram crosses negative
        sell = (rsi > 65) | ((macd_hist < 0) & (macd_hist.shift(1) >= 0))

        signals = pd.Series(0, index=df.index)
        signals[buy] = 1
        signals[sell] = -1
        return signals


class TechnicalStrategy(BaseStrategy):
    """Pure moving average crossover benchmark."""

    def __init__(self, fast: int = 20, slow: int = 50):
        self.fast = fast
        self.slow = slow

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        sma_fast = close.rolling(self.fast).mean()
        sma_slow = close.rolling(self.slow).mean()
        signals = pd.Series(0, index=df.index)
        signals[sma_fast > sma_slow] = 1
        signals[sma_fast <= sma_slow] = -1
        return signals


class IntradayORBVWAPStrategy(BaseStrategy):
    """
    Intraday day-trading strategy that mirrors the live intraday engine.

    Entry rules (long):
      - Price breaks above the Opening Range High (first orb_minutes of session)
      - Price is above session VWAP at that bar
      - 5-bar momentum is positive

    Entry rules (short):
      - Price breaks below the Opening Range Low
      - Price is below session VWAP
      - 5-bar momentum is negative

    Exit rules:
      - Price crosses back through VWAP in adverse direction (stop/reversal)
      - Last bar of the session (no overnight holds — pure day trading)
      - Fixed stop: entry_price ± stop_pct

    This strategy expects 5-minute intraday bars as input (not daily).
    Use run_intraday_backtest() in engine.py rather than the standard run_backtest().
    """

    def __init__(
        self,
        orb_minutes: int = 30,
        stop_pct: float = 0.005,   # 0.5% hard stop
        allow_short: bool = False,  # short-selling off by default (paper acct may not allow)
    ):
        self.orb_bars  = orb_minutes // 5   # number of 5-min bars in opening range
        self.stop_pct  = stop_pct
        self.allow_short = allow_short

    # generate_signals is not used — intraday sim runs per-day; see simulate_day()
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(0, index=df.index)

    def simulate_day(self, day_df: pd.DataFrame) -> list[dict]:
        """
        Simulate all trades for a single trading day.
        Returns list of trade dicts with entry/exit timestamps and P&L.
        """
        trades = []
        if len(day_df) < self.orb_bars + 2:
            return trades

        or_bars = day_df.iloc[: self.orb_bars]
        orh = float(or_bars["high"].max())
        orl = float(or_bars["low"].min())

        # Precompute VWAP at each bar (cumulative)
        typical   = (day_df["high"] + day_df["low"] + day_df["close"]) / 3.0
        cum_tpv   = (typical * day_df["volume"]).cumsum()
        cum_vol   = day_df["volume"].cumsum().replace(0, 1)
        vwap_series = cum_tpv / cum_vol

        closes  = day_df["close"].values
        highs   = day_df["high"].values
        lows    = day_df["low"].values
        vwaps   = vwap_series.values
        index   = day_df.index

        position = 0   # 0=flat, 1=long, -1=short
        entry_price = 0.0
        entry_ts    = None
        stop_price  = 0.0

        for i in range(self.orb_bars, len(day_df)):
            price = closes[i]
            vwap  = vwaps[i]
            is_last_bar = (i == len(day_df) - 1)

            # ── Exit logic ────────────────────────────────────────────────
            if position == 1:
                hit_stop = price <= stop_price
                vwap_reversal = price < vwap
                if hit_stop or vwap_reversal or is_last_bar:
                    pnl = (price - entry_price) * 100   # 100-share lot
                    trades.append({
                        "entry_ts": entry_ts, "exit_ts": index[i],
                        "side": "long",
                        "entry": entry_price, "exit": price,
                        "qty": 100, "pnl": round(pnl, 2),
                        "exit_reason": "stop" if hit_stop else ("vwap_cross" if vwap_reversal else "eod"),
                    })
                    position = 0

            elif position == -1 and self.allow_short:
                hit_stop = price >= stop_price
                vwap_reversal = price > vwap
                if hit_stop or vwap_reversal or is_last_bar:
                    pnl = (entry_price - price) * 100
                    trades.append({
                        "entry_ts": entry_ts, "exit_ts": index[i],
                        "side": "short",
                        "entry": entry_price, "exit": price,
                        "qty": 100, "pnl": round(pnl, 2),
                        "exit_reason": "stop" if hit_stop else ("vwap_cross" if vwap_reversal else "eod"),
                    })
                    position = 0

            if position != 0 or is_last_bar:
                continue

            # ── 5-bar momentum ────────────────────────────────────────────
            if i >= 5:
                mom = (closes[i] - closes[i - 5]) / max(closes[i - 5], 1e-9)
            else:
                mom = 0.0

            # ── Entry logic ───────────────────────────────────────────────
            if highs[i] > orh and price > vwap and mom > 0:
                position    = 1
                entry_price = price
                entry_ts    = index[i]
                stop_price  = price * (1 - self.stop_pct)

            elif self.allow_short and lows[i] < orl and price < vwap and mom < 0:
                position    = -1
                entry_price = price
                entry_ts    = index[i]
                stop_price  = price * (1 + self.stop_pct)

        return trades
