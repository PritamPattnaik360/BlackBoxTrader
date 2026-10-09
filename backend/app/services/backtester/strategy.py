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


class RegimeAdaptiveStrategy(BaseStrategy):
    """
    Daily long-only strategy that switches playbook with the market bias, the
    same SPY-trend + VIX score the live engine uses (market_bias.compute_bias):

      bull     → trend following: enter when close > SMA50 with positive 20-day
                 momentum; exit on a close below SMA50, a flip to bear, or -8%.
      neutral  → mean reversion: enter when RSI(5) < 30; exit RSI(5) > 60,
                 10 days held, or -5%.
      bear     → bounce only: enter when RSI(2) < 10 (washed out); exit
                 RSI(2) > 65, 5 days held, or -5%. Trend positions opened
                 earlier are closed as soon as the bias turns bear.
    """

    def __init__(self, bull_stop: float = 0.08, other_stop: float = 0.05):
        self.bull_stop = bull_stop
        self.other_stop = other_stop

    @staticmethod
    def bias_series(index: pd.DatetimeIndex) -> pd.Series:
        """Vectorised historical version of market_bias.compute_bias()."""
        import yfinance as yf
        start = (index.min() - pd.Timedelta(days=420)).strftime("%Y-%m-%d")
        end = (index.max() + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        raw = yf.download(["SPY", "^VIX"], start=start, end=end, progress=False, auto_adjust=True)
        close = raw["Close"].dropna(subset=["SPY"])
        spy = close["SPY"]
        vix = close["^VIX"].reindex(spy.index).ffill()
        ma50, ma200 = spy.rolling(50).mean(), spy.rolling(200).mean()
        ret20 = spy / spy.shift(20) - 1
        score = (
            np.where(spy > ma200, 1, -1) + np.where(ma50 > ma200, 1, -1) + np.where(spy > ma50, 1, -1)
            + np.where(ret20 > 0.02, 1, np.where(ret20 < -0.04, -1, 0))
            + np.where(vix < 18, 1, np.where(vix > 30, -2, np.where(vix > 24, -1, 0)))
        )
        bias = pd.Series(np.where(score >= 2, "bull", np.where(score <= -2, "bear", "neutral")), index=spy.index)
        bias[ma200.isna()] = "neutral"
        bias.index = bias.index.tz_localize(None) if bias.index.tz is not None else bias.index
        return bias

    @staticmethod
    def _rsi(close: pd.Series, n: int) -> pd.Series:
        d = close.diff()
        g = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
        l = (-d.clip(upper=0)).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
        return 100 - 100 / (1 + g / l.replace(0, 1e-9))

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        idx = close.index.tz_localize(None) if close.index.tz is not None else close.index
        bias = self.bias_series(idx).reindex(idx, method="ffill").fillna("neutral").values

        sma50, sma5 = close.rolling(50).mean().values, close.rolling(5).mean().values
        mom20 = (close / close.shift(20) - 1).values
        rsi2, rsi5, rsi14 = self._rsi(close, 2).values, self._rsi(close, 5).values, self._rsi(close, 14).values
        px = close.values

        sig = np.zeros(len(px), dtype=int)
        pos, mode, entry, held = 0, "", 0.0, 0
        for i in range(len(px)):
            b = bias[i]
            if pos:
                held += 1
                ret = px[i] / entry - 1
                if mode == "trend":
                    out = px[i] < sma50[i] or b == "bear" or ret < -self.bull_stop
                elif mode == "revert":
                    out = rsi5[i] > 60 or held >= 10 or ret < -self.other_stop
                else:  # bounce
                    out = rsi2[i] > 65 or px[i] > sma5[i] or held >= 5 or ret < -self.other_stop
                if out:
                    sig[i], pos = -1, 0
                continue
            if np.isnan(sma50[i]) or np.isnan(rsi14[i]):
                continue
            if b == "bull" and px[i] > sma50[i] and mom20[i] > 0 and rsi14[i] < 75:
                sig[i], pos, mode, entry, held = 1, 1, "trend", px[i], 0
            elif b == "neutral" and rsi5[i] < 30:
                sig[i], pos, mode, entry, held = 1, 1, "revert", px[i], 0
            elif b == "bear" and rsi2[i] < 10:
                sig[i], pos, mode, entry, held = 1, 1, "bounce", px[i], 0
        return pd.Series(sig, index=df.index)
