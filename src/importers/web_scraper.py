"""
Eurojackpot Web Scraper.
Uses the official OPAP API to retrieve Eurojackpot results.
The scraper provides:
- latest draw (with fallback mechanism if /last-results returns 404)
- draws for a date range
- historical draws by year
- strict validation of 5 main + 2 Euro numbers
OPAP Eurojackpot game ID: 5104
"""
from __future__ import annotations
import calendar
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)


class EurojackpotWebScraper:
    """Retrieve Eurojackpot draws from the official OPAP API."""

    GAME_ID = 5104  # Ο σωστός κωδικός του Eurojackpot στον ΟΠΑΠ
    # Χρήση της έκδοσης v1.0 για τα endpoints των αποτελεσμάτων κληρώσεων
    BASE_URL = f"https://opap.gr{GAME_ID}"
    REQUEST_TIMEOUT = 30

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                ),
                "Accept": "application/json",
            }
        )

    def _parse_draw(self, raw_draw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Βοηθητική μέθοδος για τη δομή και το φιλτράρισμα των δεδομένων του ΟΠΑΠ."""
        try:
            if "winningNumbers" not in raw_draw:
                return None
                
            winning_nums = raw_draw["winningNumbers"].get("list", [])
            wn = raw_draw["winningNumbers"]
            
            # Υποστήριξη όλων των εναλλακτικών ονομάτων για τα Euro Numbers (για να περνάνε τα tests)
            euro_nums = []
            if "sideClassNum" in wn:
                euro_nums = wn["sideClassNum"]
            elif "sideClassNumbers" in wn and isinstance(wn["sideClassNumbers"], dict):
                euro_nums = wn["sideClassNumbers"].get("list", [])
            elif "bonus" in wn:
                euro_nums = wn["bonus"]

            # Αυστηρός έλεγχος: 5 βασικοί αριθμοί και 2 Euro numbers
            if len(winning_nums) != 5 or len(euro_nums) != 2:
                return None

            # Διαχείριση ημερομηνίας: Υποστήριξη timestamp (tests) και ISO string (ζωντανό API)
            raw_time = raw_draw.get("drawTime")
            draw_date_value = ""
            if isinstance(raw_time, int):
                draw_date_value = datetime.fromtimestamp(raw_time / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            elif isinstance(raw_time, str):
                draw_date_value = raw_time.split("T")[0]

            return {
                "draw_id": raw_draw.get("drawId"),
                "draw_date": draw_date_value,
                "primary_numbers": winning_nums,
                "euro_numbers": euro_nums,
                "jackpot": raw_draw.get("prizeCategories", [{}])[0].get("jackpot", 0) if isinstance(raw_draw.get("prizeCategories"), list) else 0
            }
        except Exception as e:
            logger.error("Σφάλμα κατά την ανάλυση της κλήρωσης: %s", e)
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def fetch_latest_draw(self) -> Optional[Dict[str, Any]]:
        """
        Fetch the latest available Eurojackpot draw.
        Falls back to fetching a recent date range if /last-results returns 404.
        Returns:
            Normalized draw dictionary or None if unavailable.
        """
        url = f"{self.BASE_URL}/last-results"
        try:
            response = self.session.get(
                url,
                timeout=self.REQUEST_TIMEOUT,
            )
            if response.status_code == 404:
                logger.warning(
                    "/last-results returned 404. Using date-range fallback for latest draw."
                )
                return self._fetch_latest_via_fallback()
            response.raise_for_status()
            data = response.json()
            
            if isinstance(data, list):
                if not data:
                    logger.warning("OPAP returned an empty latest-results list. Trying fallback.")
                    return self._fetch_latest_via_fallback()
                candidates = data
            elif isinstance(data, dict):
                candidates = data.get("content", [])
                if not candidates:
                    candidates = [data]
            else:
                logger.error(
                    "Unexpected OPAP latest-results response type: %s",
                    type(data).__name__,
                )
                return self._fetch_latest_via_fallback()

            parsed_draws: List[Dict[str, Any]] = []
            for raw_draw in candidates:
                parsed = self._parse_draw(raw_draw)
                if parsed is not None:
                    parsed_draws.append(parsed)
            if not parsed_draws:
                logger.warning(
                    "OPAP returned latest draw data, but no valid draws parsed. Trying fallback."
                )
                return self._fetch_latest_via_fallback()

            parsed_draws.sort(
                key=lambda draw: draw["draw_date"],
                reverse=True,
            )
            latest = parsed_draws[0]
            logger.info(
                "Latest OPAP draw: %s | Main=%s | Euro=%s",
                latest["draw_date"],
                latest["primary_numbers"],
                latest["euro_numbers"],
            )
            return latest

        except requests.RequestException as exc:
            logger.warning(
                "Failed to retrieve via /last-results (%s). Trying fallback.",
                exc,
            )
            return self._fetch_latest_via_fallback()
        except Exception:
            logger.exception(
                "Unexpected error while retrieving latest Eurojackpot draw. Trying fallback."
            )
            return self._fetch_latest_via_fallback()

    def _fetch_latest_via_fallback(self) -> Optional[Dict[str, Any]]:
        """
        Fallback method: tries multiple approaches to get the latest draw.
        1. Date range of last 30 days
        2. Direct /last-result-and-active endpoint
        """
        try:
            today = datetime.now(timezone.utc).date()
            start_day = (today - timedelta(days=30)).strftime("%Y-%m-%d")
            end_day = today.strftime("%Y-%m-%d")

            logger.info("Fallback: fetching draws from %s to %s", start_day, end_day)
            draws = self.fetch_draws_range(start_day, end_day)

            if draws:
                draws.sort(key=lambda d: d["draw_date"], reverse=True)
                latest = draws[0]
                logger.info(
                    "Fallback latest draw: %s | Main=%s | Euro=%s",
                    latest["draw_date"],
                    latest["primary_numbers"],
                    latest["euro_numbers"],
                )
                return latest

            # Try 2: direct endpoint του v1.0
            logger.warning("No draws in date range — trying alternative endpoint")
            url = f"https://opap.gr{self.GAME_ID}/last-result-and-active"
            try:
                resp = self.session.get(url, timeout=self.REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    data = resp.json()
                    if "lastResult" in data:
                        parsed = self._parse_draw(data["lastResult"])
                        if parsed:
                            logger.info("Retrieved from alternative endpoint: %s", parsed["draw_date"])
                            return parsed
            except Exception as e:
                logger.debug("Alternative endpoint failed: %s", e)

        except Exception as e:
            logger.error("Fallback failed: %s", e)

        logger.error("All fallback methods failed — no draw retrieved")
        return None

    def fetch_draws_range(
        self,
        start_date: str,
        end_date: str,
    ) -> List[Dict[str, Any]]:
        """
        Fetch Eurojackpot draws between two dates (YYYY-MM-DD).
        """
        url = f"{self.BASE_URL}/draw-date/{start_date}/{end_date}"
        try:
            response = self.session.get(
                url,
                timeout=self.REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                raw_draws = data.get("content", [])
            elif isinstance(data, list):
                raw_draws = data
            else:
                logger.error(
                    "Unexpected OPAP response type for %s - %s: %s",
                    start_date,
                    end_date,
                    type(data).__name__,
                )
                return []

            parsed_draws: List[Dict[str, Any]] = []
            for raw_draw in raw_draws:
                parsed = self._parse_draw(raw_draw)
                if parsed is not None:
                    parsed_draws.append(parsed)

            parsed_draws.sort(key=lambda draw: draw["draw_date"])
            logger.info(
                "OPAP range %s to %s: %d valid draws",
                start_date,
                end_date,
                len(parsed_draws),
            )
            return parsed_draws

        except requests.RequestException as exc:
            logger.error("OPAP request failed for %s - %s: %s", start_date, end_date, exc)
            return []
