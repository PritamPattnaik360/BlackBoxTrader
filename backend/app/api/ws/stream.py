import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
logger = logging.getLogger(__name__)
_connections: set[WebSocket] = set()


@router.websocket("/ws/live")
async def live_stream(ws: WebSocket):
    await ws.accept()
    _connections.add(ws)
    last_sent: dict[str, str] = {}   # ticker -> bar timestamp already sent on this connection
    try:
        while True:
            # Try Redis subscription first
            from app.services.market_data.cache import subscribe_quotes
            from app.models.watchlist import Watchlist
            from app.db.session import AsyncSessionLocal
            from sqlalchemy import select

            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Watchlist).where(Watchlist.is_active == True))
                tickers = [w.ticker for w in result.scalars().all()]

            pubsub = subscribe_quotes(tickers) if tickers else None
            if pubsub:
                try:
                    msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if msg and msg.get("data"):
                        await ws.send_text(msg["data"] if isinstance(msg["data"], str) else json.dumps(msg["data"]))
                except Exception:
                    pass
            else:
                # No Redis: the Alpaca feed writes bars to the in-process cache, so push
                # any quote that changed since this client last saw it.
                from app.services.market_data.cache import get_quote
                for t in tickers:
                    q = get_quote(t)
                    if q and last_sent.get(t) != q.get("time"):
                        last_sent[t] = q.get("time")
                        try:
                            await ws.send_text(json.dumps(q))
                        except Exception:
                            return
                await asyncio.sleep(2)

            # Keepalive ping
            try:
                await ws.send_text(json.dumps({"type": "ping"}))
            except Exception:
                break

    except WebSocketDisconnect:
        pass
    finally:
        _connections.discard(ws)


async def broadcast(message: dict):
    dead = set()
    for ws in _connections:
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            dead.add(ws)
    _connections.difference_update(dead)
