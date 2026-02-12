"""
Hyatt Website Scraper
SeleniumBase-first implementation
Production-ready for GCP headless deployment
"""

import logging
import time
import re
from typing import Dict, Any, List
from seleniumbase import SB
import os
import random

logger = logging.getLogger(__name__)

def get_proxy_config():
    proxy_url = os.getenv("PROXY_URL")
    if not proxy_url:
        return None

    # Optional: rotate session per attempt (recommended)
    session_id = random.randint(100000, 999999)

    if "session-" not in proxy_url:
        # Inject Bright Data session rotation
        proxy_url = proxy_url.replace(
            "zone-",
            f"zone-session-{session_id}-"
        )

    return proxy_url

class HyattScraper:
    """Standalone Hyatt scraper using SeleniumBase (Hilton-style structure)"""

    def __init__(self, headless: bool = True, max_retries: int = 3):
        self.headless = headless
        self.max_retries = max_retries

    # ============================================================
    # Utility
    # ============================================================

    def _pause(self, seconds: float):
        time.sleep(seconds)

    def _scroll_slowly(self, sb):
        """Smooth scroll to trigger lazy loading"""
        last_height = sb.execute_script("return document.body.scrollHeight")
        while True:
            sb.execute_script("window.scrollBy(0, 800);")
            self._pause(1.5)
            new_height = sb.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

    # ============================================================
    # Extraction Methods
    # ============================================================

    def _extract_hotel_name(self, sb) -> str:
        selectors = [
            '[data-locator="property-name"]',
            "h1.be-headline-standard-1",
            "h1[class*='be-headline']",
            "h1"
        ]
        for selector in selectors:
            try:
                if sb.wait_for_element(selector, timeout=3):
                    name = sb.get_text(selector).strip()
                    if name:
                        return name
            except:
                continue
        return ""

    def _extract_description(self, sb) -> str:
        selectors = [
            "p.be-text-body-2",
            "[data-testid='property-description']",
            "section[class*='overview'] p"
        ]
        for selector in selectors:
            try:
                elements = sb.find_elements(selector)
                for el in elements:
                    text = el.text.strip()
                    if len(text) > 30:
                        return text
            except:
                continue
        return ""

    def _extract_address(self, sb) -> Dict[str, str]:
        full_address = ""
        selectors = [
            "[data-testid='property-address']",
            ".property-address",
            "address"
        ]

        for selector in selectors:
            try:
                elements = sb.find_elements(selector)
                for el in elements:
                    text = el.text.strip()
                    if "," in text:
                        full_address = text
                        break
                if full_address:
                    break
            except:
                continue

        address = city = state = country = postal_code = ""

        if full_address:
            parts = [p.strip() for p in full_address.split(",")]
            if len(parts) >= 1:
                address = parts[0]
            if len(parts) >= 2:
                city = parts[1]
            if len(parts) >= 3:
                state_zip = parts[2]
                zip_match = re.search(r"\b\d{5}(?:-\d{4})?\b", state_zip)
                if zip_match:
                    postal_code = zip_match.group()
                    state = state_zip.replace(postal_code, "").strip()
                else:
                    state = state_zip
            if len(parts) >= 4:
                country = parts[3]

        return {
            "address": address,
            "city": city,
            "state": state,
            "country": country,
            "postal_code": postal_code,
            "full_address": full_address
        }

    def _extract_phone(self, sb) -> str:
        selectors = [
            'a[href^="tel:"]',
            '[data-testid="phone-number"]'
        ]
        for selector in selectors:
            try:
                elements = sb.find_elements(selector)
                for el in elements:
                    text = el.text.strip()
                    if text:
                        return text
            except:
                continue
        return ""

    def _extract_amenities(self, sb) -> List[str]:
        amenities = []
        try:
            if sb.is_element_present('[data-locator="amenity-list-core2"]', timeout=5):
                items = sb.find_elements('[data-locator="amenity-list-core2"] li p')
                for el in items:
                    text = el.text.strip()
                    if text:
                        amenities.append(text)
        except:
            pass

        return list(dict.fromkeys(amenities))  # dedupe

    def _extract_pet_policy(self, sb) -> Dict[str, Any]:
        pet_info = {
            "policy": "",
            "fees": [],
            "weight_limits": [],
            "restrictions": []
        }

        try:
            if sb.is_element_present('[data-locator="pets-overview-text"]', timeout=6):
                full_text = sb.get_text('[data-locator="pets-overview-text"]')
                pet_info["policy"] = full_text

                lines = full_text.split("\n")
                for line in lines:
                    lower = line.lower()
                    if "$" in line or "fee" in lower:
                        pet_info["fees"].append(line)
                    if "lb" in lower or "kg" in lower:
                        pet_info["weight_limits"].append(line)
                    if "maximum" in lower or "restrict" in lower:
                        pet_info["restrictions"].append(line)
        except:
            pass

        return pet_info

    def _extract_rating(self, sb) -> str:
        selectors = [
            "[data-testid='review-rating']",
            ".rating-score"
        ]
        for selector in selectors:
            try:
                if sb.wait_for_element(selector, timeout=3):
                    text = sb.get_text(selector)
                    match = re.search(r"\d+(\.\d+)?", text)
                    if match:
                        return match.group()
            except:
                continue
        return ""

    # ============================================================
    # MAIN METHOD WITH RETRY
    # ============================================================

    def extract_all_data(self, url: str) -> Dict[str, Any]:

        attempt = 0

        while attempt < self.max_retries:
            try:
                proxy = get_proxy_config()
                with SB(
                    browser="chrome",
                    headless=self.headless,
                    undetectable=True,
                    headless2=self.headless,
                    incognito=True,
                    uc=True,
                    disable_csp=True,
                    block_images=False,
                    proxy=proxy,
                ) as sb:

                    logger.info(f"Opening {url}")
                    sb.open(url)

                    self._pause(6)
                    self._scroll_slowly(sb)

                    # Accept cookies if visible
                    cookie_selectors = [
                        "#onetrust-accept-btn-handler",
                        "button:contains('Accept')"
                    ]
                    for sel in cookie_selectors:
                        try:
                            if sb.is_element_visible(sel, timeout=2):
                                sb.click(sel)
                                self._pause(2)
                                break
                        except:
                            continue

                    hotel_name = self._extract_hotel_name(sb)
                    description = self._extract_description(sb)
                    address_info = self._extract_address(sb)
                    phone = self._extract_phone(sb)
                    amenities = self._extract_amenities(sb)
                    pet_policy = self._extract_pet_policy(sb)
                    rating = self._extract_rating(sb)

                    return {
                        "hotel_name": hotel_name,
                        "description": description,
                        "contact_info": {
                            "address": address_info["full_address"],
                            "city": address_info["city"],
                            "state": address_info["state"],
                            "country": address_info["country"],
                            "postal_code": address_info["postal_code"],
                            "phone": phone,
                        },
                        "amenities": amenities,
                        "pets_policy": pet_policy,
                        "parking_policy": "",
                        "smoking_policy": "",
                        "wifi_policy": "",
                        "rating": rating,
                        "url": url,
                        "status": "success",
                        "timestamp": time.time()
                    }

            except Exception as e:
                attempt += 1
                logger.warning(f"Retry {attempt}/{self.max_retries} due to error: {e}")
                time.sleep(5)

        return {
            "hotel_name": "",
            "description": "",
            "contact_info": {
                "address": "",
                "city": "",
                "state": "",
                "country": "",
                "postal_code": "",
                "phone": ""
            },
            "amenities": [],
            "pets_policy": {},
            "parking_policy": "",
            "smoking_policy": "",
            "wifi_policy": "",
            "rating": "",
            "url": url,
            "status": "failed",
            "timestamp": time.time()
        }


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    scraper = HyattScraper(headless=True)

    test_url = "https://www.hyatt.com/hyatt-place/en-US/yqmzm-hyatt-place-moncton-downtown"

    result = scraper.extract_all_data(test_url)

    print(result)
