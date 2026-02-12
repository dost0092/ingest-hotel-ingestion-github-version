"""
Hyatt Pet-Friendly Hotels Scraper
SeleniumBase + PostgreSQL + Resume Mechanism
Production-ready for GCP headless VM
"""

import os
import time
import logging
import psycopg2
from contextlib import contextmanager
from typing import List, Dict, Optional
from datetime import datetime
from dotenv import load_dotenv
from seleniumbase import SB

load_dotenv()

# =====================================================
# CONFIGURATION
# =====================================================

BASE_URL = "https://www.hyatt.com/landing/promo/pet-friendly-hotels-at-hyatt"

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

RETRY_LIMIT = 3
SCROLL_PAUSE = 2
WAIT_AFTER_LOAD = 15

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =====================================================
# DATABASE MANAGER
# =====================================================

class DatabaseManager:

    def __init__(self):
        self.connection_params = {
            "host": DB_HOST,
            "port": DB_PORT,
            "database": DB_NAME,
            "user": DB_USER,
            "password": DB_PASSWORD,
        }

    @contextmanager
    def get_connection(self):
        conn = None
        try:
            conn = psycopg2.connect(**self.connection_params)
            yield conn
            conn.commit()
        except Exception:
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def hotel_exists(self, url: str) -> bool:
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM hotel_mapped_url WHERE url = %s",
                    (url,)
                )
                return cur.fetchone() is not None

    def save_hotel(self, name: str, url: str, address: str):
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO hotel_mapped_url
                    (hotel_name, url, state, country_code, chain, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (url)
                    DO UPDATE SET
                        hotel_name = EXCLUDED.hotel_name,
                        updated_at = NOW()
                """, (
                    name,
                    url,
                    None,
                    None,
                    "Hyatt"
                ))

# =====================================================
# HYATT SCRAPER
# =====================================================

class HyattPetFriendlyScraper:

    def __init__(self):
        self.db = DatabaseManager()
        self.session_id = f"hyatt_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def scrape(self):
        attempt = 0
        while attempt < RETRY_LIMIT:
            try:
                self._run_scraper()
                break
            except Exception as e:
                attempt += 1
                logger.error(f"Retry {attempt}/{RETRY_LIMIT} due to error: {e}")
                time.sleep(5)

    def _run_scraper(self):

        with SB(
            browser="chrome",
            headless=True,
            undetectable=True,
            headless2=True,
            incognito=True,
            agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            uc=True,
            disable_csp=True,
            block_images=False,
        ) as sb:

            logger.info(f"Opening {BASE_URL}")
            sb.open(BASE_URL)

            logger.info("Waiting for page render")
            time.sleep(WAIT_AFTER_LOAD)

            self._scroll_until_loaded(sb)
            self._expand_all_hotels(sb)
            self._scroll_until_loaded(sb)

            hotels = self._extract_hotels(sb)
            logger.info(f"Total hotels found: {len(hotels)}")

            for hotel in hotels:
                if not self.db.hotel_exists(hotel["url"]):
                    self.db.save_hotel(
                        hotel["name"],
                        hotel["url"],
                        hotel["address"]
                    )

            logger.info("Scraping completed")

    # =====================================================
    # SCROLLING LOGIC
    # =====================================================

    def _scroll_until_loaded(self, sb):
        last_height = sb.execute_script("return document.body.scrollHeight")

        while True:
            sb.execute_script("window.scrollBy(0, 800);")
            time.sleep(SCROLL_PAUSE)

            new_height = sb.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

    # =====================================================
    # CLICK SHOW MORE HOTELS UNTIL GONE
    # =====================================================

    def _expand_all_hotels(self, sb):

        while True:
            try:
                if sb.is_element_present(
                    "//button[span[text()='Show More Hotels']]",
                    timeout=5
                ):
                    logger.info("Clicking Show More Hotels")
                    sb.click("//button[span[text()='Show More Hotels']]")
                    time.sleep(5)
                    self._scroll_until_loaded(sb)
                else:
                    break
            except Exception:
                break

    # =====================================================
    # HOTEL EXTRACTION
    # =====================================================

    def _extract_hotels(self, sb) -> List[Dict]:

        hotels = []

        cards = sb.find_elements(
            "div.styles_hotel-gallery-list__list-container__NRvPG"
        )

        for card in cards:
            try:
                link_el = card.find_element(
                    "css selector",
                    "a.styles_hotel-card__card-link__aIYgv"
                )

                url = link_el.get_attribute("href")

                name = card.find_element(
                    "css selector",
                    "div.styles_hotel-card__header-text__6t0CC"
                ).text.strip()

                address_1 = card.find_element(
                    "css selector",
                    "div.styles_hotel-card__address-1__wFSlx"
                ).text.strip()

                address_2 = card.find_element(
                    "css selector",
                    "div.styles_hotel-card__address-2__cBaYR"
                ).text.strip()

                full_address = f"{address_1}, {address_2}"

                hotels.append({
                    "name": name,
                    "url": url,
                    "address": full_address
                })

            except Exception:
                continue

        return hotels


# =====================================================
# ENTRYPOINT
# =====================================================

if __name__ == "__main__":
    scraper = HyattPetFriendlyScraper()
    scraper.scrape()
