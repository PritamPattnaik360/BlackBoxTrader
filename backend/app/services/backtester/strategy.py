import pandas as pd
import numpy as np


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
