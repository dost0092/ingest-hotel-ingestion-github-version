"""
Hilton Hotels Location Scraper
Complete scraping logic with Selenium, PostgreSQL, and state management
"""
import os
import random
import time
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from typing import Optional, List, Dict
from datetime import datetime
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType # ONLY if you really want it
import undetected_chromedriver as uc
# Load environment variables
load_dotenv()

# =====================================================
# CONFIGURATION
# =====================================================
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
RESTART_INTERVAL = int(os.getenv("RESTART_INTERVAL", "100"))

# User agents for anti-bot detection
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# North America country mappings (state-based)
NORTH_AMERICA_COUNTRIES = {
    "United States of America": "US",
    "Canada": "CA",
    "Mexico": "MX"
}

# Configure logging
logger = logging.getLogger(__name__)


# =====================================================
# DATABASE MANAGER CLASS
# =====================================================
class DatabaseManager:
    """Handles all PostgreSQL database operations"""
    
    def __init__(self):
        self.connection_params = {
            'host': DB_HOST,
            'port': DB_PORT,
            'database': DB_NAME,
            'user': DB_USER,
            'password': DB_PASSWORD
        }
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = None
        try:
            conn = psycopg2.connect(**self.connection_params)
            yield conn
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def get_country_code_from_db(self, country_name: str) -> Optional[str]:
        """Get country code from test.countries table"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT country_code FROM countries WHERE country = %s",
                        (country_name,)
                    )
                    result = cur.fetchone()
                    return result[0] if result else None
        except Exception as e:
            logger.error(f"Error fetching country code for {country_name}: {e}")
            return None
    
    def save_hotel(self, hotel_data: Dict) -> bool:
        """Save or update hotel record with Hilton brand info"""
        try:
            # Force the brand/chain to Hilton
            brand_name = "Hilton"
            
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # 1. Check if hotel exists using the URL as the unique key
                    cur.execute(
                        "SELECT id FROM hotel_mapped_url WHERE url = %s",
                        (hotel_data['url'],)
                    )
                    existing = cur.fetchone()
                    
                    if existing:
                        # 2. Update existing record
                        # Matching your query columns: hotel_name, state, country_code, chain
                        cur.execute("""
                            UPDATE hotel_mapped_url 
                            SET hotel_name = %s, 
                                state = %s, 
                                country_code = %s, 
                                chain = %s,
                                updated_at = NOW()
                            WHERE url = %s
                        """, (
                            hotel_data['name'],
                            hotel_data.get('state'),
                            hotel_data['country'], # Maps to country_code
                            brand_name,            # "Hilton"
                            hotel_data['url']
                        ))
                        logger.debug(f"Updated: {hotel_data['name']}")
                    else:
                        # 3. Insert new record
                        # Columns: hotel_name, url, state, country_code, chain, created_at, updated_at
                        cur.execute("""
                            INSERT INTO hotel_mapped_url 
                            (hotel_name, url, state, country_code, chain, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                        """, (
                            hotel_data['name'],
                            hotel_data['url'],
                            hotel_data.get('state'),
                            hotel_data['country'], # Maps to country_code
                            brand_name,            # "Hilton"
                        ))
                        logger.debug(f"Inserted: {hotel_data['name']}")
                    
                    return True
        except Exception as e:
            logger.error(f"Error saving hotel {hotel_data.get('name')}: {e}")
            return False

# =====================================================
# BROWSER MANAGER CLASS
# =====================================================
class BrowserManager:
    """Manages undetected-chromedriver with anti-bot detection for Local and GCP"""
    
    def __init__(self, headless: bool = HEADLESS):
        self.headless = headless
        self.driver: Optional[uc.Chrome] = None
        self.wait: Optional[WebDriverWait] = None
    
    def create_driver(self) -> uc.Chrome:
        """Create undetected-chromedriver with anti-bot configuration"""
        opts = uc.ChromeOptions()
        
        # Headless mode for Cloud Run/GCP
        if self.headless:
            opts.add_argument("--headless=new")
        
        # Stability and Cloud Essentials
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--remote-allow-origins=*")
        
        # Anti-bot Rotation
        opts.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
        
        try:
            # UC handles driver downloading/matching automatically
            # use_subprocess=True is recommended for Docker/GCP environments
            driver = uc.Chrome(
                options=opts, 
                use_subprocess=True,
                version_main=144 # Automatically matches your installed Chrome version
            )
            
            logger.info("Undetected WebDriver created successfully")
            return driver
        except Exception as e:
            logger.error(f"Error creating UC WebDriver: {e}")
            raise
        
    def start(self):
        """Start browser"""
        if self.driver is None:
            self.driver = self.create_driver()
            self.wait = WebDriverWait(self.driver, 25) # Slightly higher timeout for UC
            logger.info("Browser started")
    
    def restart(self):
        """Restart browser"""
        logger.info("Restarting browser...")
        self.stop()
        time.sleep(2)
        self.start()
    
    def stop(self):
        """Stop browser"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            finally:
                self.driver = None
                self.wait = None
    
    def get_url(self, url: str, max_retries: int = 3) -> bool:
        """Navigate to URL with retry"""
        for attempt in range(max_retries):
            try:
                if not self.driver:
                    self.start()

                self.driver.get(url)
                time.sleep(random.uniform(2, 4))

                # ✅ Add this right here:
                if not self.driver.title:
                    logger.warning("Empty headless render detected, restarting driver...")
                    self.restart()
                    time.sleep(3)
                    continue  # Try again with a fresh browser instance

                return True

            except Exception as e:
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {url}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)
                    self.restart()

        # If all attempts fail
        return False
    
    def wait_and_click(self, by: By, value: str, timeout: int = 15) -> bool:
        """Wait and click element"""
        try:
            element = self.wait.until(EC.element_to_be_clickable((by, value)))
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time.sleep(0.5)
            try:
                element.click()
            except:
                self.driver.execute_script("arguments[0].click();", element)
            time.sleep(random.uniform(1, 2))
            return True
        except TimeoutException:
            logger.warning(f"Timeout clicking: {value}")
            return False
        except Exception as e:
            logger.error(f"Error clicking {value}: {e}")
            return False

# =====================================================
# HILTON LOCATIONS SCRAPER CLASS
# =====================================================
class HiltonLocationsScraper:
    def __init__(self, base_url: str = "https://www.hilton.com/en/locations/"):
        self.base_url = base_url
        self.browser = BrowserManager()
        self.db = DatabaseManager()
        self.hotels_scraped = 0
        self.session_id = f"hilton_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def scrape_all_locations(self, country_code_filter: Optional[str] = None) -> Dict:
        self.browser.start()
        stats = {'total': 0, 'success': 0, 'failed': 0, 'errors': []}
        try:
            if not self.browser.get_url(self.base_url):
                raise RuntimeError("Failed to open base URL")

            # Ensure Region accordion is open
            self._open_region_accordion()

            # Get the list of proper Region tabs
            regions = self._get_region_tabs()
            logger.info(f"Found {len(regions)} regions")

            for idx, region in enumerate(regions, start=1):
                logger.info(f"Processing region {idx}/{len(regions)}: {region['name']}")
                ok = self._process_region(region, country_code_filter, stats)
                if not ok:
                    logger.warning(f"Region failed: {region['name']}")

                # Restart driver periodically for stability
                if self.hotels_scraped and self.hotels_scraped % RESTART_INTERVAL == 0:
                    self.browser.restart()
                    self.browser.get_url(self.base_url)
                    self._open_region_accordion()

            return stats
        except Exception as e:
            logger.exception(f"Top-level scrape error: {e}")
            stats['errors'].append(str(e))
            return stats
        finally:
            self.browser.stop()
    def _select_region_and_get_active_panel(self, region_name: str):
        """
        Clicks the region tab by visible text and returns the active panel WebElement.
        Ensures the tab's aria-controls panel is visible before returning.
        """
        # Find all region tabs
        tabs = self.browser.driver.find_elements(By.CSS_SELECTOR, 'div[role="tablist"] button[role="tab"]')
        target_tab = None
        for t in tabs:
            if (t.text or "").strip() == region_name:
                target_tab = t
                break

        if not target_tab:
            raise RuntimeError(f"Region tab not found: {region_name}")

        self.browser.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", target_tab)
        # Click if not selected
        if target_tab.get_attribute("aria-selected") != "true":
            try:
                target_tab.click()
            except Exception:
                self.browser.driver.execute_script("arguments[0].click();", target_tab)

        # Wait for its panel to be visible
        panel_id = target_tab.get_attribute('aria-controls')
        if not panel_id:
            raise RuntimeError(f"Region tab has no aria-controls: {region_name}")
        panel = WebDriverWait(self.browser.driver, 15).until(
            EC.visibility_of_element_located((By.ID, panel_id))
        )
        return panel
    def _open_region_accordion(self):
        try:
            # Wait for page to load completely
            time.sleep(3)
            
            # First, let's see what's on the page
            logger.info(f"Current URL: {self.browser.driver.current_url}")
            logger.info(f"Page title: {self.browser.driver.title}")
            
            # Save initial page source for debugging
            with open("initial_page.html", "w", encoding="utf-8") as f:
                f.write(self.browser.driver.page_source[:5000])  # First 5000 chars
            
            # Try to find ANY button first
            all_buttons = self.browser.driver.find_elements(By.TAG_NAME, "button")
            logger.info(f"Found {len(all_buttons)} total buttons on page")
            
            # Look for region-related buttons
            for i, btn in enumerate(all_buttons[:10]):  # Check first 10 buttons
                btn_text = btn.text.strip()
                btn_id = btn.get_attribute("id") or ""
                btn_class = btn.get_attribute("class") or ""
                if btn_text:
                    logger.info(f"Button {i}: '{btn_text}', id: '{btn_id}', class: '{btn_class}'")
            
            # Try specific selectors
            selectors = [
                'button[data-osc*="region"]',
                'button[aria-controls*="region"]', 
                'button[data-testid*="region"]',
                'button.accordion-trigger',
                'button[role="button"]',
                '#region-accordion',
                '.region-accordion button',
                'button:contains("Region")'  # If using XPath
            ]
            
            accordion = None
            for selector in selectors:
                try:
                    elements = self.browser.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        accordion = elements[0]
                        logger.info(f"Found potential accordion with selector: {selector}")
                        break
                except:
                    continue
            
            if not accordion:
                logger.error("Could not find any accordion button. Page structure may have changed.")
                # Take screenshot for debugging
                self.browser.driver.save_screenshot("no_accordion_found.png")
                return
            
            # Check if it's already expanded
            is_expanded = accordion.get_attribute("aria-expanded")
            data_state = accordion.get_attribute("data-state")
            logger.info(f"Accordion state - aria-expanded: {is_expanded}, data-state: {data_state}")
            
            if is_expanded != "true" and data_state != "open":
                self.browser.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", accordion)
                time.sleep(1)
                
                # Try to click
                try:
                    accordion.click()
                    logger.info("Clicked accordion")
                except:
                    self.browser.driver.execute_script("arguments[0].click();", accordion)
                    logger.info("Clicked accordion via JS")
                
                # Wait for expansion
                time.sleep(2)
                
                # Check if it expanded
                is_expanded = accordion.get_attribute("aria-expanded")
                logger.info(f"After click - aria-expanded: {is_expanded}")
            else:
                logger.info("Accordion already open")
                
        except Exception as e:
            logger.error(f"Error in _open_region_accordion: {e}")
            # Take screenshot to see what's happening
            try:
                self.browser.driver.save_screenshot("accordion_error.png")
            except:
                pass

    def _get_region_tabs(self) -> List[Dict]:
        regions = []
        try:
            tab_buttons = self.browser.driver.find_elements(
                By.CSS_SELECTOR, 'div[role="tablist"] button[role="tab"]'
            )
            for tab in tab_buttons:
                name = (tab.text or "").strip()
                rid = tab.get_attribute('id')
                aria_controls = tab.get_attribute('aria-controls')
                # Filter out state-level tabs if any appear; keep continent-level names
                if name and name not in ["Texas", "Florida", "California"]:
                    regions.append({'id': rid, 'name': name, 'aria_controls': aria_controls})
            if not regions:
                logger.warning("No region tabs found. Check if the element is visible.")
        except Exception as e:
            logger.error(f"Error getting region tabs: {e}", exc_info=True)
        return regions

    def _process_region(self, region: Dict, country_code_filter: Optional[str], stats: Dict) -> bool:
        try:
            # Select the region tab and get its active panel
            panel = self._select_region_and_get_active_panel(region['name'])

            # Get the countries within this panel
            countries = self._get_countries_in_region_panel(panel)
            logger.info(f"Found {len(countries)} countries in {region['name']}")

            # Deduplicate by name (some pages duplicate links)
            seen = set()
            deduped = []
            for c in countries:
                key = (c['name'], c.get('type', ''))
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(c)
            countries = deduped

            for country in countries:
                if country_code_filter:
                    ccode = self._get_country_code(country['name'], region['name'])
                    if ccode != country_code_filter:
                        continue

                self._process_country_in_panel(panel, country, region['name'], stats)

            return True
        except Exception as e:
            logger.error(f"Error processing region {region.get('name','?')}: {e}", exc_info=True)
            return False

    def _get_countries_in_region_panel(self, panel_el) -> List[Dict]:
        countries = []
        try:
            # Primary: Accordion buttons for large countries (USA, Canada, Mexico)
            # Scoped to panel to avoid cross-panel leaks
            buttons = panel_el.find_elements(By.CSS_SELECTOR, 'button[data-osc^="accordion-trigger-"]')
            for btn in buttons:
                name = (btn.text or "").strip()
                if name:
                    countries.append({
                        'name': name,
                        'type': 'accordion',
                        'aria_controls': btn.get_attribute('aria-controls')
                    })

            # Secondary: Direct links
            # Only add direct link countries that are visible and not empty
            links = panel_el.find_elements(By.TAG_NAME, 'a')
            for link in links:
                name = (link.text or "").strip()
                url = link.get_attribute('href')
                # Avoid adding “Explore”/marketing links at this stage; keep country list clean.
                if name and url and ('/locations/' in url):
                    # Heuristic: country links under a region often look like /en/locations/<country/...>
                    # We’ll still allow them, but “type: link”
                    countries.append({'name': name, 'type': 'link', 'url': url})
        except Exception as e:
            logger.error(f"Error getting countries: {e}", exc_info=True)
        return countries

    def _process_country_in_panel(self, panel_el, country_data: Dict, region_name: str, stats: Dict):
        country_name = country_data['name']
        try:
            # CASE A: Direct navigation to country page
            if country_data.get('type') == 'link':
                self._process_state(country_data, country_name, region_name, stats)
                self._reset_to_base_and_region(region_name)
                return

            # CASE B: Accordion (e.g., United States of America, Canada, Mexico)
            # Scope the search inside current panel to avoid cross-panel matches
            if country_data.get('type') == 'accordion':
                btn = None
                try:
                    # Prefer aria-controls from pre-scanned data, ensuring the correct button
                    aria_id = country_data.get('aria_controls')
                    if aria_id:
                        btn = panel_el.find_element(By.CSS_SELECTOR, f'button[aria-controls="{aria_id}"]')
                    else:
                        # Fallback by text match within panel
                        candidates = panel_el.find_elements(By.CSS_SELECTOR, 'button[data-osc^="accordion-trigger-"]')
                        for c in candidates:
                            if (c.text or "").strip() == country_name:
                                btn = c
                                break
                    if not btn:
                        raise Exception("Country accordion button not found in panel")
                except Exception as e:
                    logger.error(f"Country accordion not found: {country_name} ({e})")
                    return

                # Open accordion if not open
                is_open = btn.get_attribute("data-state") == "open" or btn.get_attribute("aria-expanded") == "true"
                if not is_open:
                    self.browser.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                    try:
                        btn.click()
                    except Exception:
                        self.browser.driver.execute_script("arguments[0].click();", btn)
                    # Wait content visible
                    aria_id = btn.get_attribute('aria-controls')
                    WebDriverWait(self.browser.driver, 10).until(
                        EC.visibility_of_element_located((By.ID, aria_id))
                    )
                    time.sleep(0.2)

                # Get states/locations inside this accordion content
                aria_id = btn.get_attribute('aria-controls')
                content_panel = self.browser.driver.find_element(By.ID, aria_id)
                states = self._get_state_links_in_content(content_panel)
                logger.info(f"Found {len(states)} states/locations in {country_name}")

                # Iterate states
                for state in states:
                    if not state['name'] or not state['url']:
                        continue
                    self._process_state(state, country_name, region_name, stats)
                    # Reset to region tab and reopen accordion for next state
                    self._reset_to_base_and_region(region_name)
                    # Re-locate the accordion button inside the freshly-activated panel
                    panel_el = self._select_region_and_get_active_panel(region_name)
                    try:
                        re_btn = panel_el.find_element(By.CSS_SELECTOR, f'button[aria-controls="{aria_id}"]')
                    except Exception:
                        # Fallback by text
                        re_btn = None
                        candidates = panel_el.find_elements(By.CSS_SELECTOR, 'button[data-osc^="accordion-trigger-"]')
                        for c in candidates:
                            if (c.text or "").strip() == country_name:
                                re_btn = c
                                break
                    if re_btn and (re_btn.get_attribute("data-state") != "open" and re_btn.get_attribute("aria-expanded") != "true"):
                        try:
                            re_btn.click()
                        except Exception:
                            self.browser.driver.execute_script("arguments[0].click();", re_btn)
                        WebDriverWait(self.browser.driver, 10).until(
                            EC.visibility_of_element_located((By.ID, aria_id))
                        )
                        time.sleep(0.2)
        except Exception as e:
            logger.error(f"Error in country {country_name}: {e}", exc_info=True)

    def _reset_to_base_and_region(self, region_name: str):
        """
        Return to the main locations page, open region accordion, select the region tab,
        and ensure its panel is visible for subsequent queries.
        """
        self.browser.get_url(self.base_url)
        self._open_region_accordion()
        # Select region and wait for active panel
        self._select_region_and_get_active_panel(region_name)
        time.sleep(0.3)
    def _get_state_links_in_content(self, content_el) -> List[Dict]:
        links = []
        try:
            # State links appear as simple anchors within the accordion content panel
            all_links = content_el.find_elements(By.TAG_NAME, 'a')
            for link in all_links:
                name = (link.text or "").strip()
                url = link.get_attribute('href')
                if name and url:
                    links.append({'name': name, 'url': url})
        except Exception as e:
            logger.error(f"Error getting state links: {e}", exc_info=True)
        return links
    def _save_hotels(self, hotels: List[Dict], country_name: str, region_name: str, state_name: str, stats: Dict):
        for hotel in hotels:
            country_code = self._get_country_code(country_name, region_name)
            hotel_data = {
                'name': hotel['name'],
                'url': hotel['url'],
                'country': country_code,
                'city': ''
            }
            if region_name == "North America":
                hotel_data['state'] = state_name

            if self.db.save_hotel(hotel_data):
                stats['success'] += 1
                self.hotels_scraped += 1
            else:
                stats['failed'] += 1
            stats['total'] += 1

    def _get_top_market_city_links(self) -> List[Dict]:
        links = []
        try:
            # First, look within the Top Market Places section if present
            try:
                top = self.browser.driver.find_element(By.ID, 'top-market-places')
                city_as = top.find_elements(By.CSS_SELECTOR, 'a[data-testid^="dynamicgrid-wom-item-link-"]')
            except Exception:
                city_as = self.browser.driver.find_elements(By.CSS_SELECTOR, 'a[data-testid^="dynamicgrid-wom-item-link-"]')

            for a in city_as:
                url = a.get_attribute('href')
                # Visible label is inside the span
                text = ""
                try:
                    text = (a.find_element(By.TAG_NAME, 'span').text or "").strip()
                except Exception:
                    text = (a.text or "").strip()
                if url and text:
                    links.append({'name': text, 'url': url})

            # Deduplicate by URL
            dedup = {}
            for l in links:
                dedup[l['url']] = l
            links = list(dedup.values())
        except Exception as e:
            logger.debug(f"No city hubs found or error reading them: {e}")
        return links

    def _process_state(self, state_link: Dict, country_name: str, region_name: str, stats: Dict):
        try:
            state_name = state_link['name']
            state_url = state_link['url']
            logger.info(f"Processing: {state_name}")

            if not self.browser.get_url(state_url):
                logger.error(f"Failed to load: {state_url}")
                return

            # Optional filter (non-blocking)
            self._apply_pet_friendly_filter()

            # Try scraping hotel cards directly
            total_found = 0
            page = 1
            hotels = self._get_hotels_on_page()
            if not hotels:
                # If no hotels found, try the city hubs (“Top Market Places”) path
                city_links = self._get_top_market_city_links()
                if city_links:
                    logger.info(f"{state_name}: found {len(city_links)} city hub(s); drilling down")
                    for city in city_links:
                        if not self.browser.get_url(city['url']):
                            logger.warning(f"Cannot open city: {city['name']}")
                            continue
                        page = 1
                        while True:
                            logger.info(f"Scraping {city['name']} page {page} of {state_name}")
                            hotels = self._get_hotels_on_page()
                            if not hotels:
                                break
                            total_found += len(hotels)
                            self._save_hotels(hotels, country_name, region_name, state_name, stats)
                            if not self._click_next_page():
                                break
                            page += 1
                else:
                    logger.info(f"{state_name}: no hotel cards and no city hubs found")
            else:
                # We are on a list page directly
                while True:
                    logger.info(f"Scraping page {page} of {state_name}")
                    if hotels:
                        total_found += len(hotels)
                        self._save_hotels(hotels, country_name, region_name, state_name, stats)
                    if not self._click_next_page():
                        break
                    page += 1
                    hotels = self._get_hotels_on_page()

            logger.info(f"Completed {state_name}; total hotels saved: {total_found}")
        except Exception as e:
            logger.error(f"Error processing {state_link.get('name','?')}: {e}", exc_info=True)
            stats['errors'].append(f"{state_link.get('name','?')}: {str(e)}")

    def _apply_pet_friendly_filter(self):
        try:
            # Keep timeout small; don’t block if absent
            self.browser.wait_and_click(By.XPATH, '//button[contains(@name, "Pet-Friendly")]', timeout=4)
            time.sleep(0.4)
        except Exception:
            logger.debug("Pet-Friendly filter not found or not clickable")

    def _get_hotels_on_page(self) -> List[Dict]:
        hotels = []
        try:
            # Wait for either card list or an empty state; do not fail hard
            WebDriverWait(self.browser.driver, 8).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'h3[data-testid="listViewPropertyName"], a[data-testid^="dynamicgrid-wom-item-link-"]'))
            )
        except TimeoutException:
            # Nothing rendered yet; proceed to explicit find attempts
            pass

        try:
            time.sleep(0.5)
            h3_elements = self.browser.driver.find_elements(By.CSS_SELECTOR, 'h3[data-testid="listViewPropertyName"]')
            for h3 in h3_elements:
                name = (h3.text or "").strip()
                # Card link is ancestor <a> or within sibling link; try both
                url = None
                try:
                    parent_link = h3.find_element(By.XPATH, 'ancestor::a[1]')
                    url = parent_link.get_attribute('href')
                except Exception:
                    pass
                if not url:
                    try:
                        # Some templates use a wrapping div then the link; go up and find nearest link
                        wrapper = h3.find_element(By.XPATH, 'ancestor::*[self::div or self::li][1]')
                        link = wrapper.find_element(By.CSS_SELECTOR, 'a[href*="/en/hotels/"]')
                        url = link.get_attribute('href')
                    except Exception:
                        pass

                if name and url:
                    hotels.append({'name': name, 'url': url})
            logger.info(f"Found {len(hotels)} hotels on page")
        except Exception as e:
            logger.error(f"Error getting hotels: {e}", exc_info=True)

        return hotels
    
    def _click_next_page(self) -> bool:
        try:
            # Prefer a robust selector; Hilton often uses ARIA or data-testid on pagination
            # Try ID first
            next_btn = None
            try:
                next_btn = self.browser.driver.find_element(By.ID, 'pagination-right')
            except Exception:
                pass

            if not next_btn:
                # Try data-testid
                candidates = self.browser.driver.find_elements(By.CSS_SELECTOR, '[data-testid="pagination-next"], button[aria-label="Next"], a[aria-label="Next"]')
                if candidates:
                    next_btn = candidates[0]

            if not next_btn:
                return False

            disabled = next_btn.get_attribute('disabled')
            aria_disabled = next_btn.get_attribute('aria-disabled')
            if (disabled is not None and disabled != False) or (aria_disabled == "true"):
                return False

            self.browser.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", next_btn)
            try:
                next_btn.click()
            except Exception:
                self.browser.driver.execute_script("arguments[0].click();", next_btn)

            # Wait a moment for new results to render
            WebDriverWait(self.browser.driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'h3[data-testid="listViewPropertyName"], a[data-testid^="dynamicgrid-wom-item-link-"]'))
            )
            time.sleep(0.3)
            return True
        except Exception:
            return False

    def _get_country_code(self, country_name: str, region_name: str) -> str:
        if region_name == "North America":
            mapping = {
                "United States of America": "US",
                "Canada": "CA",
                "Mexico": "MX"
            }
            return mapping.get(country_name, "")
        code = self.db.get_country_code_from_db(country_name)
        return code or ""