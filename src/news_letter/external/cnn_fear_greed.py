from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from news_letter.external.proxy import get_webshare_proxy


CNN_FEAR_GREED_URL = (
    "https://production.dataviz.cnn.io/"
    "index/fearandgreed/graphdata"
)


@dataclass
class FearGreedSnapshot:
    score: float
    rating: str
    timestamp: str | None
    previous_close: float | None
    previous_1_week: float | None
    previous_1_month: float | None
    previous_1_year: float | None


class CNNFearGreedClient:
    def __init__(
        self,
        *,
        timeout: float = 20.0,
    ) -> None:
        self.timeout = timeout
        self.proxies = get_webshare_proxy()

    def fetch_raw(self) -> dict[str, Any]:
        response = requests.get(
            CNN_FEAR_GREED_URL,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/134.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Referer": (
                    "https://www.cnn.com/"
                    "markets/fear-and-greed"
                ),
            },
            proxies=self.proxies,
            timeout=self.timeout,
        )

        response.raise_for_status()

        return response.json()

    def fetch_snapshot(self) -> FearGreedSnapshot:
        data = self.fetch_raw()

        fear_greed = data["fear_and_greed"]

        return FearGreedSnapshot(
            score=float(fear_greed["score"]),
            rating=str(fear_greed["rating"]),
            timestamp=fear_greed.get("timestamp"),
            previous_close=_optional_float(
                fear_greed.get("previous_close")
            ),
            previous_1_week=_optional_float(
                fear_greed.get("previous_1_week")
            ),
            previous_1_month=_optional_float(
                fear_greed.get("previous_1_month")
            ),
            previous_1_year=_optional_float(
                fear_greed.get("previous_1_year")
            ),
        )


def _optional_float(
    value: Any,
) -> float | None:
    if value is None:
        return None

    return float(value)
