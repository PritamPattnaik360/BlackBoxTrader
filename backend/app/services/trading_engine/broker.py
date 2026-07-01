import logging
from app.config import settings

logger = logging.getLogger(__name__)
_trading_client = None


def get_trading_client():
    global _trading_client
    if _trading_client is None:
        if not settings.alpaca_api_key:
            raise RuntimeError("ALPACA_API_KEY not configured")
        from alpaca.trading.client import TradingClient
        _trading_client = TradingClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
            paper=(settings.trading_mode == "paper"),
        )
    return _trading_client


def reset_client():
    """Call after switching trading_mode so client re-initializes to new URL."""
    global _trading_client
    _trading_client = None


def get_account() -> dict:
    client = get_trading_client()
    acct = client.get_account()
    return {
        "equity": float(acct.equity),
        "cash": float(acct.cash),
        "buying_power": float(acct.buying_power),
        "portfolio_value": float(acct.portfolio_value),
        "day_trade_count": acct.daytrade_count,
        "trading_blocked": acct.trading_blocked,
        "account_blocked": acct.account_blocked,
    }


def get_positions() -> list[dict]:
    client = get_trading_client()
    positions = client.get_all_positions()
    return [
        {
            "ticker": p.symbol,
            "qty": float(p.qty),
            "avg_entry_price": float(p.avg_entry_price),
            "current_price": float(p.current_price),
            "unrealized_pnl": float(p.unrealized_pl),
            "unrealized_pnl_pct": float(p.unrealized_plpc),
            "market_value": float(p.market_value),
            "asset_class": str(p.asset_class),
        }
        for p in positions
    ]


def get_open_orders() -> list[dict]:
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    client = get_trading_client()
    orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
    return [_order_to_dict(o) for o in orders]


def get_all_orders(limit: int = 100) -> list[dict]:
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    client = get_trading_client()
    orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.ALL, limit=min(limit, 500)))
    return [_order_to_dict(o) for o in orders]


def submit_market_order(ticker: str, side: str, qty: float) -> dict:
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    client = get_trading_client()
    req = MarketOrderRequest(
        symbol=ticker,
        qty=qty,
        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )
    order = client.submit_order(req)
    return _order_to_dict(order)


def submit_stop_order(ticker: str, side: str, qty: float, stop_price: float) -> dict:
    from alpaca.trading.requests import StopOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    client = get_trading_client()
    req = StopOrderRequest(
        symbol=ticker,
        qty=qty,
        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
        stop_price=round(stop_price, 2),
        time_in_force=TimeInForce.GTC,
    )
    order = client.submit_order(req)
    return _order_to_dict(order)


def cancel_order(order_id: str) -> None:
    client = get_trading_client()
    client.cancel_order_by_id(order_id)


def _order_to_dict(order) -> dict:
    return {
        "alpaca_order_id": str(order.id),
        "ticker": order.symbol,
        "side": str(order.side.value),
        "order_type": str(order.type.value),
        "qty": float(order.qty or 0),
        "status": str(order.status.value),
        "filled_qty": float(order.filled_qty or 0),
        "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
        "submitted_at": str(order.submitted_at) if order.submitted_at else None,
        "filled_at": str(order.filled_at) if order.filled_at else None,
    }
