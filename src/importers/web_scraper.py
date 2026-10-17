"""
Eurojackpot Web Scraper.
Uses robust open European public APIs with full test compatibility.
"""
from __future__ import annotations
import calendar
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)


class EurojackpotWebScraper:
    """Retrieve Eurojackpot draws from open European public APIs and test mocks."""

    GAME_ID = 5104
    PUBLIC_API_URL = "https://danskespil.dk/scapi/danskespil/numbergames/eurojackpot/completedDrawDates"
    REQUEST_TIMEOUT = 30

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def _parse_draw(self, raw_draw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Βοηθητική μέθοδος για τη δομή, το φιλτράρισμα και την επικύρωση των δεδομένων."""
        try:
            winning_nums = []
            euro_nums = []
            
            if "winningNumbers" in raw_draw:
                wn = raw_draw["winningNumbers"]
                winning_nums = wn.get("list", []) or wn.get("primary", [])
                euro_nums = wn.get("sideClassNum", []) or wn.get("sideClassNumbers", {}).get("list", []) or wn.get("bonus", [])
            elif "primaryNumbers" in raw_draw:
                winning_nums = raw_draw.get("primaryNumbers", [])
                euro_nums = raw_draw.get("euroNumbers", []) or raw_draw.get("bonusNumbers", [])

            # 1. Αυστηρός έλεγχος πλήθους: 5 βασικοί αριθμοί και 2 Euro numbers
            if len(winning_nums) != 5 or len(euro_nums) != 2:
                return None

            # 2. Αυστηρός έλεγχος τιμών (Validation): 1-50 για κύριους, 1-12 για Euro
            if any(int(num) < 1 or int(num) > 50 for num in winning_nums):
                return None
            if any(int(num) < 1 or int(num) > 12 for num in euro_nums):
                return None

            # 3. Ταξινόμηση αριθμών σε αύξουσα σειρά (Απαίτηση των tests)
            sorted_winning_nums = sorted([int(n) for n in winning_nums])
            sorted_euro_nums = sorted([int(n) for n in euro_nums])

            # Διαχείριση ημερομηνίας
            raw_time = raw_draw.get("drawTime") or raw_draw.get("date") or raw_draw.get("drawDate")
            draw_date_value = ""
            
            if isinstance(raw_time, int):
                draw_date_value = datetime.fromtimestamp(raw_time / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            elif isinstance(raw_time, str):
                draw_date_value = raw_time.split("T")[0]

            if not draw_date_value or len(draw_date_value) != 10:
                return None

            return {
                "draw_id": raw_draw.get("drawId") or raw_draw.get("id"),
                "draw_date": draw_date_value,
                "primary_numbers": sorted_winning_nums,
                "euro_numbers": sorted_euro_nums,
                "jackpot": raw_draw.get("jackpot", 0)
            }
        except Exception as e:
            logger.error("Σφάλμα κατά την ανάλυση της κλήρωσης: %s", e)
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def fetch_latest_draw(self) -> Optional[Dict[str, Any]]:
        """Fetch the latest available Eurojackpot draw."""
        try:
            response = self.session.get(self.PUBLIC_API_URL, timeout=self.REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            raw_draws = []
            if isinstance(data, list):
                raw_draws = data
            elif isinstance(data, dict):
                raw_draws = data.get("content", []) or data.get("draws", []) or [data]

            if not raw_draws:
                return None

            parsed_draws = []
            for item in raw_draws:
                parsed = self._parse_draw(item)
                if parsed:
                    parsed_draws.append(parsed)

            if not parsed_draws:
                return None

            parsed_draws.sort(key=lambda d: d["draw_date"], reverse=True)
            latest = parsed_draws[0]
            logger.info("Latest draw: %s | Main=%s | Euro=%s", latest["draw_date"], latest["primary_numbers"], latest["euro_numbers"])
            return latest

        except Exception as exc:
            logger.error("Failed to retrieve draw: %s", exc)
            return None

    def fetch_draws_range(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Fetch draws within a specific date range (YYYY-MM-DD)."""
        try:
            response = self.session.get(self.PUBLIC_API_URL, timeout=self.REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            raw_draws = []
            if isinstance(data, list):
                raw_draws = data
            elif isinstance(data, dict):
                raw_draws = data.get("content", []) or data.get("draws", []) or [data]

            if not raw_draws:
                return []

            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")

            filtered_draws = []
            for item in raw_draws:
                parsed = self._parse_draw(item)
                if parsed:
                    draw_dt = datetime.strptime(parsed["draw_date"], "%Y-%m-%d")
                    if start_dt <= draw_dt <= end_dt:
                        filtered_draws.append(parsed)

            filtered_draws.sort(key=lambda d: d["draw_date"])
            return filtered_draws
        except Exception as exc:
            logger.error("Range request failed for %s - %s: %s", start_date, end_date, exc)
            return []

    def fetch_year_draws(self, year: int) -> List[Dict[str, Any]]:
        """Fetch all draws for a specific year."""
        return self.fetch_draws_range(f"{year}-01-01", f"{year}-12-31")

    def _fetch_latest_via_fallback(self) -> Optional[Dict[str, Any]]:
        """Fallback wrapper."""
        return self.fetch_latest_draw()
