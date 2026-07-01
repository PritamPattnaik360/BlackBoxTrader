"""
LLM trading signal — 5th alpha source in the quant engine.

The local LLM (via Ollama) receives structured market context for a ticker
and returns a buy/sell/hold score in [-1, 1] that gets combined with the
other four quant signals (NLP, momentum, mean reversion, technical).

If Ollama is not running the function returns 0.0 (neutral, no effect on
the combined score) so the rest of the engine continues working normally.

The LLM is prompted with:
  - The ticker's recent signal component scores
  - The current market regime
  - The strategy's recent win rate
  - An instruction to return ONLY a JSON object

Over time, as `scripts/finetune_llm.py` produces better fine-tuned adapters,
the llm_score becomes more alpha-generative and its weight can be raised.
"""
import json
import logging
import asyncio

import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE    = "http://localhost:11434"
DEFAULT_MODEL  = "llama3.2:3b"
_TIMEOUT_SECS  = 15   # fast timeout — signal scan should not block

_SIGNAL_PROMPT = """\
You are a quantitative trading model. Given market data, output ONLY valid JSON — no prose, no markdown.

Market data for {ticker}:
- Momentum factor (12-1 month): {momentum:+.3f}
- Mean reversion (Bollinger/OU): {mean_reversion:+.3f}
- Technical signals (RSI/MACD/EMA): {technical:+.3f}
- News sentiment (NLP): {nlp:+.3f}
- Market regime: {regime}
- Strategy win rate (recent): {win_rate:.1f}%
{trendline_section}
Synthesize all factors. Scores range from -1 (strong sell) to +1 (strong buy).

Respond with ONLY this JSON:
{{"direction": "BUY" | "SELL" | "HOLD", "score": <float -1 to 1>, "confidence": <float 0 to 1>}}"""


def _build_trendline_section(td: dict | None) -> str:
    """Format trend line context for the LLM prompt."""
    if not td or td.get("support_level", 0.0) == 0.0:
        return ""
    sup  = td["support_level"]
    res  = td["resistance_level"]
    dirn = td["trend_dir"]
    if td.get("breakout"):
        action = "BREAKOUT above resistance"
    elif td.get("breakdown"):
        action = "BREAKDOWN below support"
    else:
        action = "price inside channel"
    return (
        f"- Trend lines: support=${sup:.2f}, resistance=${res:.2f}, "
        f"direction={dirn}, price action={action}\n"
    )


async def compute(
    ticker: str,
    nlp_score: float,
    momentum_score: float,
    mean_reversion_score: float,
    technical_score: float,
    regime: str = "normal",
    win_rate: float = 50.0,
    trendline_data: dict | None = None,
    model: str = DEFAULT_MODEL,
) -> float:
    """
    Ask the local LLM to synthesize all quant signals into a single score.

    Returns a float in [-1, 1]. Returns 0.0 if Ollama is unavailable
    or if the response cannot be parsed.
    """
    prompt = _SIGNAL_PROMPT.format(
        ticker=ticker,
        momentum=momentum_score,
        mean_reversion=mean_reversion_score,
        technical=technical_score,
        nlp=nlp_score,
        regime=regime,
        win_rate=win_rate,
        trendline_section=_build_trendline_section(trendline_data),
    )

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECS) as client:
            r = await client.post(
                f"{OLLAMA_BASE}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",   # Ollama JSON mode — forces valid JSON output
                    "options": {
                        "temperature": 0.1,   # near-deterministic for trading decisions
                        "num_predict": 64,    # we only need a tiny JSON response
                    },
                },
            )
            r.raise_for_status()
            raw = r.json().get("response", "")
            data = _parse_json_response(raw)
            score = float(data.get("score", 0.0))
            score = max(-1.0, min(1.0, score))
            logger.debug(f"LLM signal {ticker}: {data.get('direction')} score={score:+.3f} conf={data.get('confidence', '?')}")
            return score

    except httpx.ConnectError:
        return 0.0   # Ollama not running — silent fallback
    except Exception as e:
        logger.debug(f"LLM signal failed for {ticker}: {e}")
        return 0.0


def _parse_json_response(raw: str) -> dict:
    """Extract JSON from LLM output, handling minor formatting issues."""
    raw = raw.strip()
    # Find JSON object boundaries
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    return json.loads(raw)


async def is_available() -> bool:
    """Quick check whether Ollama is running (non-blocking, 2s timeout)."""
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            r = await client.get(f"{OLLAMA_BASE}/api/tags")
            return r.status_code == 200
    except Exception:
        return False
