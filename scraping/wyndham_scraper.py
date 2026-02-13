"""
Wyndham Production Scraper
Handles lazy loading + scroll-triggered rendering for Wyndham hotel pages.
"""

import time
import json
import logging
from typing import Dict, Any, List

from seleniumbase import SB
import os
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
    proxy_url = os.getenv("PROXY_URL")
    if proxy_url:
        logger.info("Using PROXY_URL from environment.")
        return proxy_url

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


class WyndhamScraper:
    """
    Scraper for Wyndham hotel overview pages.
    Extracts hotel name, address, description, and both standard/accessible amenities.
    """

    def __init__(self, headless: bool = True):
        self.headless = headless

    # ---------------------------------------------------------
    # SMART SCROLL UNTIL ELEMENT EXISTS
    # ---------------------------------------------------------
    def _progressive_scroll_until(self, sb, selector: str, by="css", max_scrolls: int = 20):
        """
        Scroll down the page until an element matching `selector` becomes visible.
        `by` can be 'css' or 'xpath'.
        """
        logger.info(f"Scrolling until element appears: {selector} ({by})")

        for i in range(max_scrolls):
            try:
                if by == "css":
                    if sb.is_element_visible(selector):
                        logger.info(f"✓ Found target after {i+1} scrolls")
                        return True
                else:  # xpath
                    if sb.is_element_visible(selector, by="xpath"):
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
        """Extract the hotel name from the h1 element (common on Wyndham pages)."""
        try:
            sb.wait_for_element_visible("h1", timeout=15)
            return sb.get_text("h1").strip()
        except:
            # Fallback: intro title
            try:
                return sb.get_text(".intro-title").strip()
            except:
                return ""

    # ---------------------------------------------------------
    # ADDRESS
    # ---------------------------------------------------------
    def _extract_address(self, sb) -> str:
        """Extract the full address from the map block."""
        try:
            # The address is inside a hidden-xs div with class uu-map-address
            addr = sb.get_text(".uu-map-address p").strip()
            return addr
        except:
            return ""

    # ---------------------------------------------------------
    # DESCRIPTION (intro paragraph)
    # ---------------------------------------------------------
    def _extract_description(self, sb) -> str:
        """Extract the long description from the intro section."""
        try:
            # Scroll to the description area if needed
            self._progressive_scroll_until(sb, ".description p", max_scrolls=8)
            desc = sb.get_text(".description p").strip()
            return desc
        except:
            return ""

    # ---------------------------------------------------------
    # STANDARD AMENITIES
    # ---------------------------------------------------------
    def _extract_amenities(self, sb) -> List[str]:
        """
        Extract the list of standard hotel amenities from the
        expandable-amenities section.
        """
        amenities = []
        # Ensure the section is loaded
        self._progressive_scroll_until(sb, "#expandable-amenities", max_scrolls=12)
        time.sleep(2)  # let any lazy content finish

        try:
            # The ul with class hotel-amenities
            items = sb.find_elements(
                "css selector",
                "#expandable-amenities ul.hotel-amenities li span[itemprop='name']"
            )
            logger.info(f"Found {len(items)} standard amenity items")
            for span in items:
                text = span.text.strip()
                if text:
                    amenities.append(text)
        except Exception as e:
            logger.warning(f"Could not extract standard amenities: {e}")

        return list(dict.fromkeys(amenities))  # remove duplicates

    # ---------------------------------------------------------
    # ACCESSIBLE AMENITIES
    # ---------------------------------------------------------
    def _extract_accessible_amenities(self, sb) -> List[str]:
        """
        Extract the list of accessible amenities from the
        expandable-ada-amenities section.
        """
        amenities = []
        self._progressive_scroll_until(sb, "#expandable-ada-amenities", max_scrolls=12)
        time.sleep(2)

        try:
            items = sb.find_elements(
                "css selector",
                "#expandable-ada-amenities ul.ada-amenities li span[itemprop='name']"
            )
            logger.info(f"Found {len(items)} accessible amenity items")
            for span in items:
                text = span.text.strip()
                if text:
                    amenities.append(text)
        except Exception as e:
            logger.warning(f"Could not extract accessible amenities: {e}")

        return list(dict.fromkeys(amenities))

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
            incognito=True,
            disable_csp=True,
            block_images=False,
            #proxy=proxy,
        ) as sb:

            sb.driver.set_page_load_timeout(60)

            logger.info(f"Opening: {url}")
            sb.open(url)

            sb.wait_for_element("body", timeout=30)
            time.sleep(6)

            # Accept cookies
            try:
                if sb.is_element_visible("#onetrust-accept-btn-handler", timeout=5):
                    sb.click("#onetrust-accept-btn-handler")
                    time.sleep(2)
            except:
                pass

            # -------------------------------------------------
            # HOTEL NAME
            # -------------------------------------------------
            hotel_name = ""
            try:
                sb.wait_for_element_visible("h1", timeout=15)
                hotel_name = sb.get_text("h1").strip()
            except:
                pass

            # -------------------------------------------------
            # INTRO TITLE + SUBTITLE
            # -------------------------------------------------
            intro_title = ""
            intro_subtitle = ""

            try:
                intro_title = sb.get_text(".intro-title").strip()
            except:
                pass

            try:
                intro_subtitle = sb.get_text(".intro-subtitle").strip()
            except:
                pass

            # -------------------------------------------------
            # DESCRIPTION
            # -------------------------------------------------
            description = ""
            try:
                sb.wait_for_element_visible(".description p", timeout=15)
                description = sb.get_text(".description p").strip()
            except:
                pass

            # -------------------------------------------------
            # BRIGHT AMENITIES SECTION DESCRIPTION
            # -------------------------------------------------
            bright_amenities_desc = ""
            try:
                sb.wait_for_element_visible(".content-desc-sec p", timeout=15)
                bright_amenities_desc = sb.get_text(".content-desc-sec p").strip()
            except:
                pass

            # -------------------------------------------------
            # ADDRESS
            # -------------------------------------------------
            address = ""
            try:
                sb.wait_for_element_visible(".uu-map-address p", timeout=15)
                address = sb.get_text(".uu-map-address p").strip()
            except:
                pass

            # -------------------------------------------------
            # STANDARD AMENITIES
            # -------------------------------------------------
            amenities = []
            try:
                sb.wait_for_element_visible("#expandable-amenities", timeout=20)

                items = sb.find_elements(
                    "css selector",
                    "#expandable-amenities ul.hotel-amenities li span[itemprop='name']"
                )

                for item in items:
                    text = item.text.strip()
                    if text:
                        amenities.append(text)

            except Exception as e:
                logger.warning(f"Amenities extraction failed: {e}")

            # -------------------------------------------------
            # ACCESSIBLE AMENITIES
            # -------------------------------------------------
            accessible_amenities = []
            try:
                sb.wait_for_element_visible("#expandable-ada-amenities", timeout=20)

                items = sb.find_elements(
                    "css selector",
                    "#expandable-ada-amenities ul.ada-amenities li span[itemprop='name']"
                )

                for item in items:
                    text = item.text.strip()
                    if text:
                        accessible_amenities.append(text)

            except Exception as e:
                logger.warning(f"Accessible amenities extraction failed: {e}")

            return {
                "hotel_name": hotel_name,
                "intro_title": intro_title,
                "intro_subtitle": intro_subtitle,
                "description": description,
                "bright_amenities_description": bright_amenities_desc,
                "address": address,
                "amenities": list(dict.fromkeys(amenities)),
                "accessible_amenities": list(dict.fromkeys(accessible_amenities)),
                "url": url,
                "status": "success" if hotel_name else "failed"
            }


# ---------------------------------------------------------
# RUN TEST
# ---------------------------------------------------------
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO)

    scraper = WyndhamScraper(headless=True)  # set False to watch the browser

    # Example URL – replace with any Wyndham / La Quinta property
    url = "https://www.wyndhamhotels.com/laquinta/la-habra-california/la-quinta-inn-and-suites-la-habra/overview"

    result = scraper.extract_all_data(url)

    print(json.dumps(result, indent=2))