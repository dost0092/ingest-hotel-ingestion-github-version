"""
Hyatt Website Scraper - COMPLETE PRODUCTION FIX
Based on proven local extraction methods
Works on Windows, Linux (GCP), and macOS
"""
import logging
import time
import re
import json
import tempfile
import os
import subprocess
import atexit
from typing import Dict, Any, List
from urllib.parse import urlparse
from seleniumbase import SB
from dotenv import load_dotenv
from pathlib import Path
# -------------------------------------------------------------------
# Logging configuration
# -------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

env_path = Path(__file__).resolve().parent / ".env"
print("Loading .env from:", env_path)

load_dotenv(dotenv_path=env_path)

# -------------------------------------------------------------------
# Tinyproxy for authenticated proxies (unchanged, works on Linux)
# -------------------------------------------------------------------
TINYPROXY_CONFIG = "/tmp/tinyproxy_hyatt.conf"
TINYPROXY_PORT = 8888
_tinyproxy_process = None

def _start_tinyproxy(upstream_url):
    global _tinyproxy_process
    parsed = urlparse(upstream_url)
    upstream_host = parsed.hostname
    upstream_port = parsed.port or 12321
    username = parsed.username
    password = parsed.password

    if username and password:
        upstream_auth = f"http://{username}:{password}@{upstream_host}:{upstream_port}"
    else:
        upstream_auth = f"http://{upstream_host}:{upstream_port}"

    config = f"""
Port {TINYPROXY_PORT}
Listen 127.0.0.1
Timeout 30
Upstream http {upstream_auth}
"""
    with open(TINYPROXY_CONFIG, "w") as f:
        f.write(config)

    subprocess.run(["sudo", "pkill", "-f", TINYPROXY_CONFIG], stderr=subprocess.DEVNULL)
    time.sleep(1)

    _tinyproxy_process = subprocess.Popen(
        ["sudo", "tinyproxy", "-c", TINYPROXY_CONFIG, "-d"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(2)
    atexit.register(_stop_tinyproxy)

def _stop_tinyproxy():
    if _tinyproxy_process:
        _tinyproxy_process.terminate()
        _tinyproxy_process.wait()
    subprocess.run(["sudo", "pkill", "-f", TINYPROXY_CONFIG], stderr=subprocess.DEVNULL)

def get_proxy_config():
    proxy_url = os.getenv("PROXY_URL")
    if not proxy_url:
        return None
    if "@" not in proxy_url:
        return proxy_url
    _start_tinyproxy(proxy_url)
    return f"127.0.0.1:{TINYPROXY_PORT}"


class HyattScraper:
    """Complete Hyatt scraper – now with reliable pet policy extraction"""

    def __init__(self, headless: bool = True, max_retries: int = 3, debug: bool = False):
        self.headless = headless
        self.max_retries = max_retries
        self.debug = debug
        self.temp_dir = tempfile.gettempdir()   # cross‑platform temp folder

    # -------------------------------------------------------------------
    # Helper methods – improved for reliability
    # -------------------------------------------------------------------
    def _pause(self, seconds: float):
        time.sleep(seconds)

    def _scroll_page(self, sb):
        """Scroll step by step, exactly as in the working local script"""
        try:
            logger.info("Scrolling page to load content...")
            sb.execute_script("window.scrollTo(0, 1000);")
            self._pause(2)
            sb.execute_script("window.scrollTo(0, 2000);")
            self._pause(2)
            sb.execute_script("window.scrollTo(0, 3000);")
            self._pause(2)
            # No scroll back – we want lazy‑loaded content to stay
        except Exception as e:
            logger.warning(f"Scroll error: {e}")

    def _save_debug_info(self, sb, prefix="debug"):
        """Save screenshot + HTML to system temp folder (works everywhere)"""
        if self.debug:
            try:
                screenshot_path = os.path.join(self.temp_dir, f"{prefix}_screenshot.png")
                html_path = os.path.join(self.temp_dir, f"{prefix}_page.html")
                sb.save_screenshot(screenshot_path)
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(sb.get_page_source())
                logger.info(f"Debug files saved: {screenshot_path}, {html_path}")
            except Exception as e:
                logger.warning(f"Could not save debug info: {e}")

    def _wait_for_element_text(self, sb, selector: str, timeout: int = 10) -> str:
        """
        Wait for an element to be visible AND contain non‑empty text.
        Returns the stripped text, or empty string if timeout.
        """
        try:
            # 1. Wait for element to be present/visible
            sb.wait_for_element_visible(selector, timeout=timeout)
            # 2. Wait for its text to become non‑empty (poll every 0.5s)
            text = ""
            for _ in range(timeout * 2):
                text = sb.get_text(selector).strip()
                if text:
                    break
                self._pause(0.5)
            return text
        except Exception as e:
            logger.debug(f"Could not get text from {selector}: {e}")
            return ""

    def _safe_get_text(self, sb, selector: str, timeout: int = 5) -> str:
        """Safely get text – with optional waiting"""
        try:
            if timeout > 0:
                sb.wait_for_element_visible(selector, timeout=timeout)
            return sb.get_text(selector).strip()
        except:
            return ""

    # -------------------------------------------------------------------
    # Extraction methods – all enhanced with proper waits
    # -------------------------------------------------------------------
    def _extract_hotel_name(self, sb) -> str:
        logger.info("Extracting hotel name...")
        selectors = [
            'h1[data-locator="property-name"]',
            'h1.property-name',
            'h1[class*="headline"]',
            'div[data-locator="find-hotels"] h1',
            'h1',
        ]
        for selector in selectors:
            text = self._safe_get_text(sb, selector, timeout=2)
            if text and len(text) > 3 and not text.lower().startswith("book"):
                logger.info(f"✓ Found hotel name: {text[:50]}")
                return text
        # Fallback: page title
        try:
            title = sb.get_title()
            if title and "Hyatt" in title:
                clean_title = title.split("|")[0].split("-")[0].strip()
                if len(clean_title) > 5:
                    logger.info(f"✓ Extracted from title: {clean_title}")
                    return clean_title
        except:
            pass
        logger.warning("Could not extract hotel name")
        return ""

    def _extract_description(self, sb) -> str:
        logger.info("Extracting description...")
        selectors = [
            '[data-locator="property-description"]',
            '[data-testid="property-description"]',
            'p.property-description',
            'div[class*="overview"] p',
            'section[class*="description"] p',
        ]
        for selector in selectors:
            try:
                if sb.is_element_present(selector, timeout=3):
                    elements = sb.find_elements(selector)
                    for el in elements:
                        text = el.text.strip()
                        if len(text) > 50:
                            logger.info(f"✓ Found description ({len(text)} chars)")
                            return text
            except:
                continue
        logger.warning("Could not extract description")
        return ""

    def _extract_address(self, sb) -> Dict[str, str]:
        logger.info("Extracting address...")
        full_address = ""
        selectors = [
            '[data-locator="property-address"]',
            '[data-testid="property-address"]',
            'address',
            '.property-address',
            '[class*="address"]',
        ]
        for selector in selectors:
            text = self._safe_get_text(sb, selector, timeout=2)
            if text and ("," in text or len(text) > 10):
                full_address = text
                logger.info(f"✓ Found address: {full_address[:50]}")
                break

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
        logger.info("Extracting phone...")
        selectors = [
            'a[href^="tel:"]',
            '[data-testid="phone-number"]',
            '[data-locator="phone"]',
            '.phone-number',
        ]
        for selector in selectors:
            try:
                if sb.is_element_present(selector, timeout=2):
                    elements = sb.find_elements(selector)
                    for el in elements:
                        text = el.text.strip()
                        if text and len(text) > 5:
                            logger.info(f"✓ Found phone: {text}")
                            return text
                        href = el.get_attribute("href")
                        if href and href.startswith("tel:"):
                            phone = href.replace("tel:", "").strip()
                            logger.info(f"✓ Found phone from href: {phone}")
                            return phone
            except:
                continue
        logger.warning("Could not extract phone")
        return ""

    def _extract_amenities(self, sb) -> List[str]:
        logger.info("Extracting amenities...")
        amenities = []
        selectors = [
            '[data-locator="amenity-list-core2"] li',
            '[data-locator="amenity-list-core2"] li p',
            '[data-testid="amenities"] li',
            '.amenities-list li',
            '[class*="amenity"] li',
        ]
        for selector in selectors:
            try:
                if sb.is_element_present(selector, timeout=5):
                    items = sb.find_elements(selector)
                    for el in items:
                        text = el.text.strip()
                        if text and len(text) > 2:
                            amenities.append(text)
                    if amenities:
                        logger.info(f"✓ Found {len(amenities)} amenities")
                        break
            except:
                continue
        return list(dict.fromkeys(amenities))

    # -------------------------------------------------------------------
    # ⭐⭐⭐ COMPLETELY REWORKED PET POLICY EXTRACTION ⭐⭐⭐
    # -------------------------------------------------------------------
    def _extract_pet_policy(self, sb) -> Dict[str, Any]:
        """
        Extract pet policy – now waits for the element to have real text,
        exactly like the local script that worked.
        """
        logger.info("Extracting pet policy...")
        pet_info = {
            "policy": "",
            "fees": [],
            "weight_limits": [],
            "restrictions": [],
            "welcome_text": "",
            "fee_details": []
        }

        # ----- STRATEGY 1: data-locator (proven to work) -----
        try:
            logger.info("Trying data-locator='pets-overview-text'...")
            # Wait for element AND for its text to become non‑empty
            policy_text = self._wait_for_element_text(
                sb, '[data-locator="pets-overview-text"]', timeout=15
            )
            if policy_text:
                logger.info(f"✅ FOUND pets-overview-text! ({len(policy_text)} chars)")
                pet_info["policy"] = policy_text

                # Parse common pet‑policy lines
                lines = policy_text.split("\n")
                for line in lines:
                    lower = line.lower()
                    if "$" in line or "fee" in lower or "charge" in lower:
                        pet_info["fees"].append(line.strip())
                    if "lb" in lower or "kg" in lower or "pound" in lower or "weight" in lower:
                        pet_info["weight_limits"].append(line.strip())
                    if ("maximum" in lower or "restrict" in lower or
                        "not allow" in lower or "prohibited" in lower):
                        pet_info["restrictions"].append(line.strip())

                # ----- Welcome text (first child div) -----
                try:
                    welcome = self._wait_for_element_text(
                        sb, '[data-locator="pets-overview-text"] div:first-of-type', timeout=3
                    )
                    if welcome:
                        pet_info["welcome_text"] = welcome
                        logger.info("✓ Extracted welcome text")
                except:
                    pass

                # ----- Fee section & individual items -----
                try:
                    if sb.is_element_present('[data-locator="pet-policy-fees"]', timeout=3):
                        fees_text = self._wait_for_element_text(
                            sb, '[data-locator="pet-policy-fees"]', timeout=3
                        )
                        if fees_text:
                            logger.info("✓ Found pet fees section")
                            # Individual fee items
                            try:
                                fee_items = sb.find_elements('[data-locator="pet-policy-fees-item"]')
                                for item in fee_items:
                                    item_text = item.text.strip()
                                    if item_text:
                                        pet_info["fee_details"].append(item_text)
                                logger.info(f"✓ Extracted {len(pet_info['fee_details'])} fee items")
                            except:
                                pass
                except:
                    pass

                return pet_info   # success, stop here

        except Exception as e:
            logger.debug(f"Data-locator method failed: {e}")

        # ----- STRATEGY 2: XPath fallback -----
        logger.info("Trying XPath selectors...")
        xpaths = [
            "//*[@id='__next']/main/div[12]/div/div/div[1]",
            "/html/body/div[1]/main/div[12]/div/div/div[1]",
            "//*[contains(text(), 'Pets Are Welcome')]/ancestor::div[contains(@data-locator, 'pets')]",
            "//div[contains(@data-locator, 'pets-overview')]",
        ]
        for xpath in xpaths:
            try:
                if sb.is_element_present(xpath, timeout=3):
                    element = sb.find_element(xpath)
                    text = element.text.strip()
                    if text and len(text) > 20:
                        logger.info("✓ Found with XPath")
                        pet_info["policy"] = text
                        # simple parse
                        for line in text.split("\n"):
                            lower = line.lower()
                            if "$" in line or "fee" in lower:
                                pet_info["fees"].append(line.strip())
                            if "lb" in lower or "kg" in lower:
                                pet_info["weight_limits"].append(line.strip())
                        return pet_info
            except:
                continue

        # ----- STRATEGY 3: Page source fallback -----
        logger.info("Searching in page source...")
        try:
            page_source = sb.driver.page_source
            if 'Pets Are Welcome' in page_source or 'pet' in page_source.lower():
                start = page_source.find('data-locator="pets-overview-text"')
                if start != -1:
                    html_slice = page_source[start:start+5000]
                    clean_text = re.sub('<[^>]+>', ' ', html_slice)
                    clean_text = ' '.join(clean_text.split())
                    if len(clean_text) > 50:
                        logger.info("✓ Extracted from page source")
                        pet_info["policy"] = clean_text[:1000]
        except Exception as e:
            logger.debug(f"Page source search failed: {e}")

        if pet_info["policy"]:
            logger.info("✓ Pet policy extracted successfully (fallback)")
        else:
            logger.warning("Could not extract pet policy")
        return pet_info

    def _extract_rating(self, sb) -> str:
        logger.info("Extracting rating...")
        selectors = [
            '[data-testid="review-rating"]',
            '.rating-score',
            '[class*="rating"]',
            '[data-locator="rating"]',
        ]
        for selector in selectors:
            text = self._safe_get_text(sb, selector, timeout=2)
            if text:
                match = re.search(r"(\d+\.?\d*)\s*(?:/|out of)", text)
                if match:
                    rating = match.group(1)
                    logger.info(f"✓ Found rating: {rating}")
                    return rating
        logger.warning("Could not extract rating")
        return ""

    # -------------------------------------------------------------------
    # Main extraction flow – now with small pause after scrolling
    # -------------------------------------------------------------------
    def extract_all_data(self, url: str) -> Dict[str, Any]:
        proxy = get_proxy_config()
        logger.info(f"proxy url is here")
        for attempt in range(1, self.max_retries + 1):
            logger.info(f"{'='*70}")
            logger.info(f"Attempt {proxy}/ {attempt}/{self.max_retries}")
            logger.info(f"{'='*70}")
            try:
                with SB(
                    browser="chrome",
                    headless=self.headless,
                    undetectable=True,
                    headless2=True,
                    incognito=True,
                    agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    uc=True,
                    disable_csp=True,
                    block_images=False,
                    #proxy=proxy,
                ) as sb:
                    sb.driver.set_page_load_timeout(60)
                    logger.info(f"🌐 Navigating to: {url}")
                    sb.open(url)

                    # --- CRITICAL: initial wait (same as local script) ---
                    logger.info("⏳ Waiting for page load (15 seconds)...")
                    self._pause(30)

                    # --- Optional cookie consent (doesn't harm) ---
                    cookie_selectors = [
                        "#onetrust-accept-btn-handler",
                        "button:contains('Accept')",
                        "button:contains('Accept All')",
                    ]
                    for sel in cookie_selectors:
                        try:
                            if sb.is_element_visible(sel, timeout=2):
                                sb.click(sel)
                                logger.info("✓ Clicked cookie consent")
                                self._pause(2)
                                break
                        except:
                            continue

                    # --- Scroll to trigger lazy loading ---
                    self._scroll_page(sb)

                    # --- EXTRA 3‑SECOND PAUSE (exactly like local script) ---
                    self._pause(3)

                    # --- Save debug info (cross‑platform) ---
                    self._save_debug_info(sb, f"attempt_{attempt}")

                    # --- Extract everything ---
                    logger.info("\n🔍 Starting data extraction...")
                    logger.info("="*70)

                    hotel_name = self._extract_hotel_name(sb)
                    description = self._extract_description(sb)
                    address_info = self._extract_address(sb)
                    phone = self._extract_phone(sb)
                    amenities = self._extract_amenities(sb)
                    pet_policy = self._extract_pet_policy(sb)   # <- now fixed
                    rating = self._extract_rating(sb)

                    # --- Summary ---
                    logger.info("="*70)
                    logger.info("Extraction Summary:")
                    logger.info(f"  Hotel Name: {'✓' if hotel_name else '✗'}")
                    logger.info(f"  Description: {'✓' if description else '✗'}")
                    logger.info(f"  Address: {'✓' if address_info['full_address'] else '✗'}")
                    logger.info(f"  Phone: {'✓' if phone else '✗'}")
                    logger.info(f"  Amenities: {len(amenities)} found")
                    logger.info(f"  Pet Policy: {'✓' if pet_policy['policy'] else '✗'}")
                    logger.info(f"  Rating: {'✓' if rating else '✗'}")
                    logger.info("="*70)

                    # --- Build result ---
                    result = {
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
                        "status": "success" if (hotel_name or address_info["full_address"] or amenities) else "failed",
                        "timestamp": time.time()
                    }

                    if result['status'] == 'success':
                        logger.info("✅ EXTRACTION SUCCESSFUL!")
                        return result
                    else:
                        logger.warning("⚠️ No meaningful data extracted")

            except Exception as e:
                logger.error(f"❌ Error on attempt {attempt}: {str(e)}")
                import traceback
                traceback.print_exc()

            # --- Wait before retry ---
            if attempt < self.max_retries:
                wait_time = 10 * attempt
                logger.info(f"Waiting {wait_time}s before retry...")
                time.sleep(wait_time)

        # --- All retries failed ---
        logger.error("❌ ALL RETRY ATTEMPTS FAILED")
        return {
            "hotel_name": "",
            "description": "",
            "contact_info": {
                "address": "", "city": "", "state": "",
                "country": "", "postal_code": "", "phone": ""
            },
            "amenities": [],
            "pets_policy": {
                "policy": "", "fees": [], "weight_limits": [],
                "restrictions": [], "welcome_text": "", "fee_details": []
            },
            "parking_policy": "", "smoking_policy": "", "wifi_policy": "",
            "rating": "", "url": url, "status": "failed", "timestamp": time.time()
        }
def clean_memory():
    """Force kill hanging chrome processes to free up RAM in GCP"""
    logger.info("Cleaning up hanging Chrome processes...")
    os.system("pkill -f chrome")
    os.system("pkill -f chromedriver")

# -------------------------------------------------------------------
# Standalone test
# -------------------------------------------------------------------
if __name__ == "__main__":
    clean_memory()
    scraper = HyattScraper(headless=True, debug=True, max_retries=2)
    test_urls = [
        "https://www.hyatt.com/hyatt-place/en-US/ontza-hyatt-place-ontario-airport"
    ]
    for url in test_urls:
        logger.info("\n" + "="*70)
        logger.info(f"TESTING: {url}")
        logger.info("="*70)
        result = scraper.extract_all_data(url)
        logger.info("\n" + "="*70)
        logger.info("FINAL RESULT:")
        logger.info("="*70)
        print(json.dumps(result, indent=2))
        logger.info("\n" + "="*70)