"""Curated liquid-perpetual research universe, not an investment recommendation.
Markets must also pass live liquidity, spread, trend, and risk filters.
"""
RESEARCH_COINS = frozenset((
    "BTC", "ETH", "SOL", "HYPE", "XRP", "DOGE", "LINK", "AVAX", "SUI", "ARB"
))
MIN_24H_VOLUME_USD = 20_000_000
MAX_BID_ASK_SPREAD_BPS = 12
