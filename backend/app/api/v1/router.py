from fastapi import APIRouter
from app.api.v1 import portfolio, orders, signals, watchlist, market_data, backtest, analytics, settings, adaptive, advisor

router = APIRouter(prefix="/api/v1")
router.include_router(portfolio.router)
router.include_router(orders.router)
router.include_router(signals.router)
router.include_router(watchlist.router)
router.include_router(market_data.router)
router.include_router(backtest.router)
router.include_router(analytics.router)
router.include_router(settings.router)
router.include_router(adaptive.router)
router.include_router(advisor.router)
