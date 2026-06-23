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
