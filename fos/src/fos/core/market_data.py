"""Market data fetcher using Yahoo Finance API.

Provides market data events for the simulation environment.
Uses yfinance library for data retrieval when available.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fos.core.external_event import ExternalEvent, ExternalEventType, EventSource, Severity

logger = logging.getLogger(__name__)


class MarketDataFetcher:
    """Fetcher for market and economic data.

    Supports Yahoo Finance via yfinance library.
    Falls back to HTTP requests if yfinance is not available.
    """

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        poll_interval_minutes: int = 10,
    ) -> None:
        """Initialize the market data fetcher.

        Args:
            symbols: List of ticker symbols to track (e.g., ["^GSPC", "^IXIC"]).
            poll_interval_minutes: How often to poll for new data.
        """
        self.symbols = symbols or ["^GSPC", "^IXIC", "^VIX"]  # S&P 500, NASDAQ, VIX
        self.poll_interval = poll_interval_minutes * 60
        self._last_data: Dict[str, Any] = {}
        self._yfinance_available = self._check_yfinance()

    def _check_yfinance(self) -> bool:
        """Check if yfinance is available."""
        try:
            import yfinance  # noqa: F401
            return True
        except ImportError:
            logger.warning("yfinance not installed. Market data will use HTTP fallback.")
            return False

    async def fetch(self) -> List[ExternalEvent]:
        """Fetch market data and create events.

        Returns:
            List of ExternalEvents for significant market changes.
        """
        events = []

        if self._yfinance_available:
            events.extend(await self._fetch_with_yfinance())
        else:
            events.extend(await self._fetch_with_http())

        return events

    async def _fetch_with_yfinance(self) -> List[ExternalEvent]:
        """Fetch data using yfinance library."""
        import yfinance as yf

        events = []

        for symbol in self.symbols:
            try:
                ticker = yf.Ticker(symbol)
                data = ticker.history(period="1d")

                if data.empty:
                    continue

                latest = data.iloc[-1]
                prev_close = data.iloc[-2]["Close"] if len(data) > 1 else latest["Close"]

                change_pct = ((latest["Close"] - prev_close) / prev_close) * 100

                event = ExternalEvent.create(
                    event_type=ExternalEventType.MARKET,
                    source=EventSource.YAHOO_FINANCE,
                    title=f"Market Update: {symbol}",
                    content=f"{symbol}: {latest['Close']:.2f} ({change_pct:+.2f}%)",
                    severity=self._get_severity(change_pct),
                    metadata={
                        "symbol": symbol,
                        "price": float(latest["Close"]),
                        "change_percent": float(change_pct),
                        "volume": int(latest["Volume"]) if "Volume" in latest else 0,
                    },
                )
                events.append(event)

                self._last_data[symbol] = {
                    "price": latest["Close"],
                    "change_percent": change_pct,
                    "timestamp": datetime.now(),
                }

            except Exception as e:
                logger.error(f"Error fetching {symbol}: {e}")

        return events

    async def _fetch_with_http(self) -> List[ExternalEvent]:
        """Fallback HTTP-based fetching using Yahoo Finance API endpoint.

        Note: This is a simplified implementation without authentication.
        For production, use yfinance library.
        """
        import urllib.request
        import json

        events = []

        for symbol in self.symbols:
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = json.loads(response.read().decode())

                result = data.get("chart", {}).get("result", [])
                if not result:
                    continue

                meta = result[0].get("meta", {})
                price = meta.get("regularMarketPrice")
                prev_close = meta.get("previousClose")

                if price and prev_close:
                    change_pct = ((price - prev_close) / prev_close) * 100

                    event = ExternalEvent.create(
                        event_type=ExternalEventType.MARKET,
                        source=EventSource.YAHOO_FINANCE,
                        title=f"Market Update: {symbol}",
                        content=f"{symbol}: {price:.2f} ({change_pct:+.2f}%)",
                        severity=self._get_severity(change_pct),
                        metadata={
                            "symbol": symbol,
                            "price": float(price),
                            "change_percent": float(change_pct),
                        },
                    )
                    events.append(event)

            except Exception as e:
                logger.error(f"Error fetching {symbol} via HTTP: {e}")

        return events

    def _get_severity(self, change_percent: float) -> Severity:
        """Determine event severity based on price change percentage."""
        abs_change = abs(change_percent)

        if abs_change > 5:
            return Severity.CRITICAL
        if abs_change > 3:
            return Severity.HIGH
        if abs_change > 1:
            return Severity.MEDIUM
        return Severity.LOW

    def get_last_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get the last fetched data for a symbol."""
        return self._last_data.get(symbol)
