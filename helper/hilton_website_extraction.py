import os
import hashlib
import logging
from typing import Dict, Any

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException

logger = logging.getLogger(__name__)

# =====================================================
# SCRAPING FUNCTIONS FROM YOUR FIRST CODE
# =====================================================

def make_uc_options(headless=False):
    """Create undetected Chrome options"""
    opts = uc.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1920,1080")
    return opts

def click_tab(driver, wait, tab_id, panel_id):
    """Clicks a tab button and waits until its panel becomes visible."""
    # Click the button
    btn = wait.until(EC.element_to_be_clickable((By.ID, tab_id)))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
    btn.click()
    # Wait for panel visible
    panel = wait.until(EC.visibility_of_element_located((By.ID, panel_id)))
    return panel

def parse_parking_html(container_el):
    """Parse parking tab content"""
    items = {}
    lis = container_el.find_elements(By.CSS_SELECTOR, "li")
    for li in lis:
        cols = li.find_elements(By.CSS_SELECTOR, ".flex-1, p, div")
        # more robust: capture the two relevant <p> in each row
        ps = li.find_elements(By.TAG_NAME, "p")
        if len(ps) >= 2:
            label = ps[0].text.strip()
            val = ps[1].text.strip()
            if label:
                items[label] = val
    return items

def parse_pets_html(container_el):
    """Parse pets tab content"""
    items = {}
    lis = container_el.find_elements(By.CSS_SELECTOR, "li")
    for li in lis:
        ps = li.find_elements(By.TAG_NAME, "p")
        if len(ps) >= 2:
            label = ps[0].text.strip()
            val = ps[1].text.strip()
            if label:
                items[label] = val
    return items

def parse_smoking_html(container_el):
    """Parse smoking tab content"""
    text_el = None
    try:
        text_el = container_el.find_element(By.CSS_SELECTOR, "[data-testid='policy-smoking']")
    except NoSuchElementException:
        pass

    # Fallback: just get first <p>
    if not text_el:
        ps = container_el.find_elements(By.TAG_NAME, "p")
        if ps:
            return ps[0].text.strip()
        return ""
    return text_el.text.strip()

def parse_wifi_html(container_el):
    """Parse WiFi tab content"""
    text_el = None
    try:
        text_el = container_el.find_element(By.CSS_SELECTOR, "[data-testid='policy-wifi']")
    except NoSuchElementException:
        pass

    # Fallback: just first <p>
    if not text_el:
        ps = container_el.find_elements(By.TAG_NAME, "p")
        if ps:
            return ps[0].text.strip()
        return ""
    return text_el.text.strip()

def parse_amenities(driver):
    """Parse amenities grid"""
    try:
        header = driver.find_element(By.CSS_SELECTOR, "[data-testid='icon-grid-header']")
    except NoSuchElementException:
        return []

    # The UL with many LI grid items
    ul_candidates = driver.find_elements(By.CSS_SELECTOR, "[data-testid='icon-grid-container'] ul")
    labels = []
    for ul in ul_candidates:
        items = ul.find_elements(By.CSS_SELECTOR, "li")
        for li in items:
            # Direct label accessor
            try:
                p = li.find_element(By.CSS_SELECTOR, "[data-testid^='grid-item-label-']")
                lbl = p.text.strip()
                if lbl:
                    labels.append(lbl)
            except NoSuchElementException:
                # fallback to aria-label
                aria = li.get_attribute("aria-label") or ""
                aria = aria.strip()
                if aria:
                    labels.append(aria)
    # unique while keeping order
    seen = set()
    out = []
    for x in labels:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def scrape_hilton_policies(url: str, wait_timeout: int = 25) -> Dict[str, Any]:
    """
    Main scraping function that extracts policies and amenities from Hilton website.
    
    Args:
        url: Hilton hotel URL
        wait_timeout: Selenium wait timeout in seconds
        
    Returns:
        Dictionary containing scraped data
    """
    driver = uc.Chrome(options=make_uc_options())
    wait = WebDriverWait(driver, wait_timeout)
    
    try:
        logger.info(f"Opening URL: {url}")
        driver.get(url)
        wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        
        # Extract hotel name and basic info
        hotel_name = ""
        try:
            name_element = driver.find_element(By.CSS_SELECTOR, "h1[data-testid='hotel-name']")
            hotel_name = name_element.text.strip()
        except NoSuchElementException:
            logger.warning("Could not find hotel name")
        
        # Extract description
        description = ""
        try:
            desc_element = driver.find_element(By.CSS_SELECTOR, "[data-testid='property-description']")
            description = desc_element.text.strip()
        except NoSuchElementException:
            logger.warning("Could not find property description")
        
        # Extract address and contact info
        contact_info = {}
        try:
            address_element = driver.find_element(By.CSS_SELECTOR, "[data-testid='property-address']")
            contact_info['address'] = address_element.text.strip()
        except NoSuchElementException:
            contact_info['address'] = ""
        
        # Extract phone if available
        try:
            phone_element = driver.find_element(By.CSS_SELECTOR, "[data-testid='property-phone']")
            contact_info['phone'] = phone_element.text.strip()
        except NoSuchElementException:
            contact_info['phone'] = ""
        
        # Click through policy tabs
        # Parking
        parking_policy = {}
        try:
            parking_panel = click_tab(driver, wait, "policies-tab-0", "tab-panel-policies-tab-0")
            parking_policy = parse_parking_html(parking_panel)
        except Exception as e:
            logger.warning(f"Could not scrape parking policy: {e}")

        # Pets
        pets_policy = {}
        try:
            pets_panel = click_tab(driver, wait, "policies-tab-1", "tab-panel-policies-tab-1")
            pets_policy = parse_pets_html(pets_panel)
        except Exception as e:
            logger.warning(f"Could not scrape pets policy: {e}")

        # Smoking
        smoking_policy = ""
        try:
            smoking_panel = click_tab(driver, wait, "policies-tab-2", "tab-panel-policies-tab-2")
            smoking_policy = parse_smoking_html(smoking_panel)
        except Exception as e:
            logger.warning(f"Could not scrape smoking policy: {e}")

        # WiFi
        wifi_policy = ""
        try:
            wifi_panel = click_tab(driver, wait, "policies-tab-3", "tab-panel-policies-tab-3")
            wifi_policy = parse_wifi_html(wifi_panel)
        except Exception as e:
            logger.warning(f"Could not scrape WiFi policy: {e}")

        # Amenities (grid)
        amenities = []
        try:
            amenities = parse_amenities(driver)
        except Exception as e:
            logger.warning(f"Could not scrape amenities: {e}")

        # Extract rating if available
        rating = ""
        try:
            rating_element = driver.find_element(By.CSS_SELECTOR, "[data-testid='review-rating']")
            rating = rating_element.text.strip()
        except NoSuchElementException:
            pass
        
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
        
    finally:
        try:
            driver.quit()
        except Exception:
            pass

# =====================================================
# INTEGRATION WITH YOUR PIPELINE
# =====================================================

class HiltonScraper:
    """Wrapper class for easy integration with your pipeline"""
    
    def __init__(self, headless=False):
        self.headless = headless
        
    def extract_all_data(self, url: str) -> Dict[str, Any]:
        """
        Main method to extract all data from Hilton website.
        This can replace hilton_website_extraction.HiltonTemplate
        """
        return scrape_hilton_policies(url)