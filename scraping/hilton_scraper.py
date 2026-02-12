"""
Hilton website scraper - SeleniumBase version
Preserves original extraction structure
Headless + Undetectable
Production safe
"""

import logging
import time
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

class HiltonScraper:
    """Standalone Hilton scraper using SeleniumBase"""

    def __init__(self, headless: bool = True, max_retries: int = 3):
        self.headless = headless
        self.max_retries = max_retries

    # ---------------------------------------------------------
    # Utilities
    # ---------------------------------------------------------

    def _pause(self, seconds: float):
        time.sleep(seconds)

    def _scroll_slow(self, sb):
        last_height = sb.execute_script("return document.body.scrollHeight")
        while True:
            sb.execute_script("window.scrollBy(0, 800);")
            self._pause(1.5)
            new_height = sb.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

    # ---------------------------------------------------------
    # TAB CLICKER (same logic as original)
    # ---------------------------------------------------------

    def _click_tab(self, sb, tab_id: str, panel_id: str):
        try:
            if sb.is_element_present(f"#{tab_id}", timeout=5):
                sb.click(f"#{tab_id}")
                self._pause(1)
                sb.wait_for_element(f"#{panel_id}", timeout=5)
                return True
        except Exception as e:
            logger.warning(f"Tab click failed: {tab_id} | {e}")
        return False

    # ---------------------------------------------------------
    # POLICY PARSERS (unchanged structure)
    # ---------------------------------------------------------

    def _parse_list_policy(self, sb, panel_id: str) -> Dict[str, str]:
        items = {}
        try:
            if sb.is_element_present(f"#{panel_id}", timeout=3):
                lis = sb.find_elements(f"#{panel_id} li")
                for li in lis:
                    ps = li.find_elements("tag name", "p")
                    if len(ps) >= 2:
                        label = ps[0].text.strip()
                        val = ps[1].text.strip()
                        if label:
                            items[label] = val
        except Exception as e:
            logger.warning(f"Policy parse error: {e}")
        return items

    def _parse_text_policy(self, sb, panel_id: str, data_testid: str) -> str:
        try:
            if sb.is_element_present(f"[data-testid='{data_testid}']", timeout=3):
                return sb.get_text(f"[data-testid='{data_testid}']")
        except:
            pass
        return ""

    # ---------------------------------------------------------
    # AMENITIES
    # ---------------------------------------------------------

    def _parse_amenities(self, sb) -> List[str]:
        labels = []
        selectors = [
            "[data-testid^='grid-item-label-']",
            ".amenity-item",
            "[class*='amenity'] p",
            ".facility-item",
            "li[aria-label]"
        ]

        for selector in selectors:
            try:
                elements = sb.find_elements(selector)
                for el in elements:
                    text = el.text.strip()
                    if text:
                        labels.append(text)
                if labels:
                    break
            except:
                continue

        # Deduplicate
        seen = set()
        unique = []
        for x in labels:
            if x not in seen:
                seen.add(x)
                unique.append(x)

        return unique

    # ---------------------------------------------------------
    # MAIN EXTRACTION
    # ---------------------------------------------------------

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

                    logger.info(f"Opening URL: {url}")
                    sb.open(url)

                    self._pause(4)
                    self._scroll_slow(sb)

                    # -------------------------------------------------
                    # HOTEL NAME
                    # -------------------------------------------------

                    hotel_name = ""
                    xpaths = [
                        "//h1[contains(@class,'heading--base')]",
                        "//*[@id='__next']//h1"
                    ]

                    for xp in xpaths:
                        try:
                            if sb.is_element_present(f"xpath={xp}", timeout=3):
                                hotel_name = sb.get_text(f"xpath={xp}")
                                if hotel_name:
                                    break
                        except:
                            continue

                    # -------------------------------------------------
                    # DESCRIPTION
                    # -------------------------------------------------

                    description = ""
                    desc_xpaths = [
                        "//p[contains(@class,'text--base')]",
                        "//*[@id='__next']//div[contains(@class,'container')]//p"
                    ]

                    for xp in desc_xpaths:
                        try:
                            if sb.is_element_present(f"xpath={xp}", timeout=3):
                                description = sb.get_text(f"xpath={xp}")
                                if description:
                                    break
                        except:
                            continue

                    # -------------------------------------------------
                    # ADDRESS + PHONE
                    # -------------------------------------------------

                    contact_info = {"address": "", "phone": ""}

                    address_selectors = [
                        "[data-testid='property-address']",
                        "span.underline-offset-2"
                    ]

                    for sel in address_selectors:
                        try:
                            if sb.is_element_present(sel, timeout=2):
                                contact_info["address"] = sb.get_text(sel)
                                break
                        except:
                            continue

                    phone_selectors = [
                        "[data-testid='property-phone']",
                        "[href^='tel:']"
                    ]

                    for sel in phone_selectors:
                        try:
                            if sb.is_element_present(sel, timeout=2):
                                contact_info["phone"] = sb.get_text(sel)
                                break
                        except:
                            continue

                    # -------------------------------------------------
                    # POLICIES
                    # -------------------------------------------------

                    parking_policy = {}
                    pets_policy = {}
                    smoking_policy = ""
                    wifi_policy = ""

                    if sb.is_element_present("[role='tablist']", timeout=3):

                        if self._click_tab(sb, "policies-tab-0", "tab-panel-policies-tab-0"):
                            parking_policy = self._parse_list_policy(sb, "tab-panel-policies-tab-0")

                        if self._click_tab(sb, "policies-tab-1", "tab-panel-policies-tab-1"):
                            pets_policy = self._parse_list_policy(sb, "tab-panel-policies-tab-1")

                        if self._click_tab(sb, "policies-tab-2", "tab-panel-policies-tab-2"):
                            smoking_policy = self._parse_text_policy(
                                sb,
                                "tab-panel-policies-tab-2",
                                "policy-smoking"
                            )

                        if self._click_tab(sb, "policies-tab-3", "tab-panel-policies-tab-3"):
                            wifi_policy = self._parse_text_policy(
                                sb,
                                "tab-panel-policies-tab-3",
                                "policy-wifi"
                            )

                    # -------------------------------------------------
                    # AMENITIES
                    # -------------------------------------------------

                    amenities = self._parse_amenities(sb)

                    # -------------------------------------------------
                    # RATING
                    # -------------------------------------------------

                    rating = ""
                    rating_selectors = [
                        "[data-testid='review-rating']",
                        ".rating-score"
                    ]

                    for sel in rating_selectors:
                        try:
                            if sb.is_element_present(sel, timeout=2):
                                rating = sb.get_text(sel)
                                break
                        except:
                            continue

                    return {
                        "hotel_name": hotel_name,
                        "description": description,
                        "contact_info": contact_info,
                        "amenities": amenities,
                        "parking_policy": parking_policy,
                        "pets_policy": pets_policy,
                        "smoking_policy": smoking_policy,
                        "wifi_policy": wifi_policy,
                        "rating": rating,
                        "url": url
                    }

            except Exception as e:
                attempt += 1
                logger.warning(f"Retry {attempt}/{self.max_retries} due to error: {e}")
                time.sleep(5)

        return {
            "hotel_name": "",
            "description": "",
            "contact_info": {"address": "", "phone": ""},
            "amenities": [],
            "parking_policy": {},
            "pets_policy": {},
            "smoking_policy": "",
            "wifi_policy": "",
            "rating": "",
            "url": url
        }


# ---------------------------------------------------------
# TEST
# ---------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    scraper = HiltonScraper(headless=True)

    test_url = "https://www.hilton.com/en/hotels/nyccnqq-hilton-new-york-times-square/"

    data = scraper.extract_all_data(test_url)

    print(data)
