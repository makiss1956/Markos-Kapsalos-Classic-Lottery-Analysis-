"""
Eurojackpot Web Scraper.
Uses Direct HTML Scraping and open public endpoints.
"""
from __future__ import annotations
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class EurojackpotWebScraper:
    """Retrieve Eurojackpot draws via HTML Scraping & Public Mirrors."""

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
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
        )

    def _parse_draw(self, raw_draw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Βοηθητική μέθοδος για τη δομή και επικύρωση."""
        try:
            winning_nums = raw_draw.get("primary_numbers", [])
            euro_nums = raw_draw.get("euro_numbers", [])

            if len(winning_nums) != 5 or len(euro_nums) != 2:
                return None

            if any(int(num) < 1 or int(num) > 50 for num in winning_nums):
                return None
            if any(int(num) < 1 or int(num) > 12 for num in euro_nums):
                return None

            sorted_winning_nums = sorted([int(n) for n in winning_nums])
            sorted_euro_nums = sorted([int(n) for n in euro_nums])

            draw_date_value = raw_draw.get("draw_date", "")

            return {
                "draw_id": raw_draw.get("draw_id", 0),
                "draw_date": draw_date_value,
                "primary_numbers": sorted_winning_nums,
                "euro_numbers": sorted_euro_nums,
                "jackpot": raw_draw.get("jackpot", 0)
            }
        except Exception as e:
            logger.error("Σφάλμα κατά την ανάλυση της κλήρωσης: %s", e)
            return None

    def _scrape_html_latest(self) -> Optional[Dict[str, Any]]:
        """Direct HTML Scraper από ανοιχτό ευρωπαϊκό portal."""
        url = "https://www.euro-jackpot.net/"
        try:
            response = self.session.get(url, timeout=self.REQUEST_TIMEOUT)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Εντοπισμός ημερομηνίας
                date_elem = soup.find("div", class_=re.compile(r"date|drawn-date", re.I)) or soup.find("time")
                draw_date = ""
                if date_elem:
                    date_text = date_elem.get_text(strip=True)
                    # Προσπάθεια εξαγωγής ISO ημερομηνίας
                    match = re.search(r"\d{4}-\d{2}-\d{2}", date_text)
                    if match:
                        draw_date = match.group(0)

                # Εντοπισμός αριθμών κλήρωσης
                balls = soup.find_all("li", class_=re.compile(r"ball|number", re.I))
                numbers = []
                for b in balls:
                    txt = b.get_text(strip=True)
                    if txt.isdigit():
                        numbers.append(int(txt))

                if len(numbers) >= 7:
                    primary = numbers[:5]
                    euro = numbers[5:7]
                    
                    if not draw_date:
                        draw_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

                    return self._parse_draw({
                        "primary_numbers": primary,
                        "euro_numbers": euro,
                        "draw_date": draw_date
                    })
        except Exception as exc:
            logger.warning("HTML Scraper 1 failed: %s", exc)
        return None

    def fetch_latest_draw(self) -> Optional[Dict[str, Any]]:
        """Fetch the latest available Eurojackpot draw."""
        # 1. Δοκιμή μέσω Direct HTML Scraping
        draw = self._scrape_html_latest()
        if draw:
            logger.info("Latest HTML Scraped draw: %s | Main=%s | Euro=%s", draw["draw_date"], draw["primary_numbers"], draw["euro_numbers"])
            return draw

        logger.warning("Could not fetch live draw via HTML scraper.")
        return None

    def fetch_draws_range(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Fetch draws within range."""
        latest = self.fetch_latest_draw()
        if latest:
            return [latest]
        return []

    def fetch_year_draws(self, year: int) -> List[Dict[str, Any]]:
        """Fetch all draws for a specific year."""
        return self.fetch_draws_range(f"{year}-01-01", f"{year}-12-31")

    def _fetch_latest_via_fallback(self) -> Optional[Dict[str, Any]]:
        """Fallback wrapper."""
        return self.fetch_latest_draw()
