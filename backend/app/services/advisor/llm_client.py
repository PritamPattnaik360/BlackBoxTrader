"""
Ollama HTTP client.

Calls the Ollama REST API at http://localhost:11434.
No Python package needed — uses httpx which is already in the stack.

Setup for the user:
  1. Install Ollama from https://ollama.com/download
  2. Run: ollama pull llama3.2:3b   (small, fast, runs on CPU)
  3. Ollama starts automatically; verify at http://localhost:11434

If Ollama is not running, all calls return a graceful error message.
"""
import httpx
import logging

logger = logging.getLogger(__name__)

OLLAMA_BASE = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2:3b"

_SYSTEM_PROMPT = """You are BlackBox Advisor, an expert quantitative trading analyst embedded in the BlackBoxTrader platform.

You have deep knowledge of:
- Quantitative finance: momentum factors, mean reversion, Sharpe ratio, Kelly criterion
- Technical analysis: RSI, MACD, Bollinger Bands, EMA crossovers
- Risk management: position sizing, stop-loss, drawdown limits
- NLP sentiment analysis for financial news (FinBERT)
- Algorithmic trading strategies used by quant hedge funds

You have access to this portfolio's live trading context (signals, positions, performance) provided in each message.
Always ground your answers in the data provided. Be concise, specific, and actionable.
When recommending a trade, always include: direction, confidence, key risk, and suggested stop-loss level.
Never make up data — if something is not in the context, say so."""


async def is_available() -> bool:
    """Ping Ollama to see if it's running."""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{OLLAMA_BASE}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


async def list_models() -> list[str]:
    """Return names of locally pulled Ollama models."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{OLLAMA_BASE}/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


async def chat(
    user_message: str,
    context: str = "",
    model: str = DEFAULT_MODEL,
    history: list[dict] | None = None,
) -> str:
    """
    Send a chat message to Ollama and return the assistant reply.

    Args:
        user_message: The user's question or request.
        context:      Structured market/portfolio context to inject as system data.
        model:        Ollama model name (default: llama3.2:3b).
        history:      Previous [{"role": "user"|"assistant", "content": "..."}] turns.
    """
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]

    if context:
        messages.append({
            "role": "system",
            "content": f"--- CURRENT PORTFOLIO & MARKET CONTEXT ---\n{context}\n--- END CONTEXT ---",
        })

    if history:
        messages.extend(history[-10:])  # keep last 10 turns to stay within context

    messages.append({"role": "user", "content": user_message})

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{OLLAMA_BASE}/api/chat",
                json={"model": model, "messages": messages, "stream": False},
            )
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
    except httpx.ConnectError:
        return (
            "**Ollama is not running.**\n\n"
            "To enable the AI advisor:\n"
            "1. Download Ollama from https://ollama.com/download\n"
            "2. Install and run it\n"
            "3. Open a terminal and run: `ollama pull llama3.2:3b`\n"
            "4. Ollama will start automatically on port 11434\n\n"
            "Once running, ask me anything about your portfolio."
        )
    except Exception as e:
        logger.error(f"Ollama chat error: {e}")
        return f"Advisor error: {e}"


async def pull_model(model: str = DEFAULT_MODEL) -> dict:
    """
    Initiate a model pull. Returns immediately — pull runs in background on Ollama side.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{OLLAMA_BASE}/api/pull",
                json={"name": model, "stream": False},
                timeout=30,
            )
            r.raise_for_status()
            return {"status": "pulling", "model": model}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
