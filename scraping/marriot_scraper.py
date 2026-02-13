
"""
Marriott Production Scraper
Handles lazy loading + scroll-triggered rendering.
"""

import time
import re
import json
import logging
from typing import Dict, Any, List
from seleniumbase import SB
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

def get_proxy_config():
    """
    Builds proxy config from environment.
    Priority:
    1. PROXY_URL (full string)
    2. PROXY_HOST + PROXY_PORT + PROXY_USER + PROXY_PASS
    """

    # If full URL provided → use directly
    proxy_url = os.getenv("PROXY_URL")
    if proxy_url:
        logger.info("Using PROXY_URL from environment.")
        return proxy_url

    # Otherwise build from parts
    host = os.getenv("PROXY_HOST")
    port = os.getenv("PROXY_PORT")
    user = os.getenv("PROXY_USER")
    password = os.getenv("PROXY_PASS")

    if host and port:
        if user and password:
            proxy = f"http://{user}:{password}@{host}:{port}"
            logger.info("Using authenticated proxy from host/port.")
            return proxy
        else:
            proxy = f"http://{host}:{port}"
            logger.info("Using proxy without authentication.")
            return proxy

    logger.info("No proxy configured.")
    return None

class MarriottScraper:

    def __init__(self, headless: bool = True):
        self.headless = headless

    # ---------------------------------------------------------
    # SMART SCROLL UNTIL ELEMENT EXISTS
    # ---------------------------------------------------------
    def _progressive_scroll_until(self, sb, xpath: str, max_scrolls: int = 20):
        logger.info(f"Scrolling until element appears: {xpath}")

        for i in range(max_scrolls):
            try:
                if sb.is_element_visible(xpath):
                    logger.info(f"✓ Found target after {i+1} scrolls")
                    return True
            except:
                pass

            sb.execute_script("window.scrollBy(0, 700);")
            time.sleep(1.5)

        logger.warning("Target not found after scrolling")
        return False

    # ---------------------------------------------------------
    # HOTEL NAME
    # ---------------------------------------------------------
    def _extract_hotel_name(self, sb) -> str:
        try:
            sb.wait_for_element_visible("h1", timeout=15)
            return sb.get_text("h1").strip()
        except:
            return ""

    # ---------------------------------------------------------
    # AMENITIES (FEATURED AMENITIES ON-SITE)
    # ---------------------------------------------------------
    def _extract_amenities(self, sb) -> List[str]:
        amenities = []

        self._progressive_scroll_until(
            sb,
            "//*[@id='main']//h2[contains(text(),'FEATURED AMENITIES')]",
            max_scrolls=10
        )

        time.sleep(3)

        li_elements = sb.find_elements(
            "css selector",
            "ul.hotel-experiences__property-amenities-list li.hotel-experiences__property-amenities-list-item"
        )

        logger.info(f"Found {len(li_elements)} amenity elements")

        for li in li_elements:
            try:
                text = li.text  # <-- USE THIS

                if text:
                    clean = text.strip().split("\n")[0].strip()
                    if clean:
                        amenities.append(clean)

            except:
                continue

        return list(dict.fromkeys(amenities))


    # ---------------------------------------------------------
    # HOTEL INFORMATION BLOCK
    # ---------------------------------------------------------
    def _extract_hotel_info(self, sb):
        import time

        info = {
            "check_in": "",
            "check_out": "",
            "minimum_age": "",
            "pet_policy": "",
            "parking_policy": ""
        }

        # Scroll until Check-in appears
        found = self._progressive_scroll_until(
            sb,
            "//*[contains(text(),'Check-in')]",
            max_scrolls=15
        )

        if not found:
            return info

        time.sleep(2)

        # -----------------------
        # CHECK-IN
        # -----------------------
        try:
            checkin = sb.find_element(
                "xpath",
                "//*[contains(text(),'Check-in')]/following::span[1]"
            )
            info["check_in"] = checkin.text.strip()
        except:
            pass

        # -----------------------
        # CHECK-OUT
        # -----------------------
        try:
            checkout = sb.find_element(
                "xpath",
                "//*[contains(text(),'Check-out')]/following::span[1]"
            )
            info["check_out"] = checkout.text.strip()
        except:
            pass

        # -----------------------
        # MINIMUM AGE
        # -----------------------
        try:
            age = sb.find_element(
                "xpath",
                "//*[contains(text(),'Minimum Age')]/following::span[1]"
            )
            info["minimum_age"] = age.text.strip()
        except:
            pass

        # -----------------------
        # PET POLICY
        # -----------------------
        try:
            pet = sb.find_element(
                "xpath",
                "//*[contains(text(),'Pet Policy')]/following::*[1]"
            )
            info["pet_policy"] = pet.text.strip()
        except:
            pass

        # -----------------------
        # PARKING POLICY
        # -----------------------
        try:
            parking = sb.find_element(
                "xpath",
                "//*[contains(text(),'Parking')]/following::*[1]"
            )
            info["parking_policy"] = parking.text.strip()
        except:
            pass

        return info




    # ---------------------------------------------------------
    # MAIN EXTRACTION FLOW
    # ---------------------------------------------------------
    def extract_all_data(self, url: str) -> Dict[str, Any]:
        proxy = get_proxy_config()
        with SB(
            browser="chrome",
            headless=self.headless,
            uc=True,
            undetectable=True,
            headless2=True,
            incognito=True,
            disable_csp=True,
            block_images=False,
            proxy=proxy,
        ) as sb:

            sb.driver.set_page_load_timeout(60)

            logger.info(f"Opening: {url}")
            sb.open(url)

            logger.info("Waiting initial load...")
            time.sleep(25)

            # Click cookies if visible
            try:
                if sb.is_element_visible("#onetrust-accept-btn-handler", timeout=5):
                    sb.click("#onetrust-accept-btn-handler")
                    time.sleep(2)
            except:
                pass

            hotel_name = self._extract_hotel_name(sb)
            amenities = self._extract_amenities(sb)
            hotel_info = self._extract_hotel_info(sb)

            return {
                "hotel_name": hotel_name,
                "amenities": amenities,
                "hotel_information": hotel_info,
                "url": url,
                "status": "success" if hotel_name else "failed"
            }


# ---------------------------------------------------------
# RUN TEST
# ---------------------------------------------------------
if __name__ == "__main__":

    scraper = MarriottScraper(headless=True)

    url = "https://www.marriott.com/en-us/hotels/bdlfe-fairfield-inn-and-suites-springfield-enfield/overview/"

    result = scraper.extract_all_data(url)

    print(json.dumps(result, indent=2))
