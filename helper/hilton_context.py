"""
Hotel Extraction Pipeline with Context Hashing, Attributes, and Slug Generation
"""
import logging
import hashlib
import re
import unicodedata
import json
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime

import psycopg2
from openai import OpenAI
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, SessionNotCreatedException
from google.genai import Client
from google.genai.types import GenerateContentConfig, Part
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum
from typing import Generic, TypeVar, cast

logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
OPENAI_API_KEY = "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"
MODEL_ID = "openai/gpt-oss-120b"

# Database configuration
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "kruiz-dev-sql",
    "user": "postgres",
    "password": "dost"
}

# Gemini API Configuration (you'll need to add your own settings)
GEMINI_CONFIG = {
    "project_id": None,  # Add your project ID
    "location": None,    # Add your location
}

# ==================== UTILITY FUNCTIONS ====================
def _normalize_context(context: str) -> str:
    """Normalize context by removing extra spaces and newlines"""
    return context.strip().lower().replace(" ", "").replace("\n", " ")

def _hash_context(context: str) -> str:
    """Generate MD5 hash of normalized context"""
    normalized_context = _normalize_context(context)
    return hashlib.md5(normalized_context.encode("utf-8")).hexdigest()

def remove_accents(text: str) -> str:
    """Remove accents from characters (é → e, ñ → n, etc.)"""
    if not text:
        return ""
    nfd = unicodedata.normalize('NFD', text)
    return ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')

def normalize_address_slug(address: str) -> str:
    """Normalize address for slug generation"""
    if not address:
        return ""
    
    val = str(address).strip()
    val = remove_accents(val)
    val = val.lower()
    val = re.sub(r"[^a-z0-9]", "", val)
    return val

def generate_combined_slug(country_code: str, state_code: str, city: str, 
                          hotel_name: str, address_line_1: str) -> Optional[str]:
    """Generate slug from all components"""
    if not state_code or not state_code.strip():
        return None
    if not address_line_1 or not address_line_1.strip():
        return None
    
    country_norm = normalize_address_slug(country_code)
    state_norm = normalize_address_slug(state_code)
    city_norm = normalize_address_slug(city)
    name_norm = normalize_address_slug(hotel_name)
    address_norm = normalize_address_slug(address_line_1)
    
    parts = [country_norm, state_norm, city_norm, name_norm, address_norm]
    parts = [p for p in parts if p]
    
    slug = "-".join(parts)
    return slug

def parse_address(address_str: str) -> Dict[str, str]:
    """
    Parse address string into components
    Example: "225 E. Apache Blvd, Tempe, Arizona, 85281, USA"
    """
    if not address_str:
        return {"address_line_1": "", "city": "", "state": "", "zip": "", "country": "", "country_code": ""}
    
    # Remove extra spaces and split by comma
    parts = [part.strip() for part in address_str.split(',')]
    
    # Default values
    address_line_1 = parts[0] if len(parts) > 0 else ""
    city = parts[1] if len(parts) > 1 else ""
    state = parts[2] if len(parts) > 2 else ""
    zip_code = parts[3] if len(parts) > 3 else ""
    country = parts[4] if len(parts) > 4 else ""
    
    # Extract country code (first two letters)
    country_code = country[:2].upper() if country else "US"
    
    return {
        "address_line_1": address_line_1,
        "city": city,
        "state": state,
        "zip": zip_code,
        "country": country,
        "country_code": country_code
    }

# ==================== DATABASE FUNCTIONS ====================
def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(**DB_CONFIG)

def save_raw_extraction(url: str, raw_content: str, hash_value: str, 
                       hotel_name: str = "", address: str = "") -> int:
    """
    Save raw extraction to database and return the ID
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Parse address if available
        address_info = parse_address(address) if address else {}
        
        # Insert or update in hotel_mapped_url table
        sql = """
        INSERT INTO test.hotel_mapped_url (
            url, hotel_name, city, state, country, country_code,
            hash, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (url) 
        DO UPDATE SET 
            hotel_name = EXCLUDED.hotel_name,
            city = EXCLUDED.city,
            state = EXCLUDED.state,
            country = EXCLUDED.country,
            country_code = EXCLUDED.country_code,
            hash = EXCLUDED.hash,
            updated_at = NOW()
        RETURNING id;
        """
        
        cur.execute(sql, (
            url,
            hotel_name,
            address_info.get("city", ""),
            address_info.get("state", ""),
            address_info.get("country", ""),
            address_info.get("country_code", "US"),
            hash_value
        ))
        
        record_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"Saved raw extraction for {url} with ID: {record_id}")
        return record_id
        
    except Exception as e:
        logger.error(f"Error saving raw extraction: {e}")
        raise

def save_web_context(record_id: int, web_context: str):
    """Save web context to database"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        sql = """
        UPDATE test.hotel_mapped_url
        SET web_context = %s,
            updated_at = NOW()
        WHERE id = %s;
        """
        
        cur.execute(sql, (web_context, record_id))
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"Saved web context for record ID: {record_id}")
        
    except Exception as e:
        logger.error(f"Error saving web context: {e}")
        raise

def save_pet_attributes(record_id: int, pet_attributes: Dict[str, Any]):
    """Save pet attributes as JSONB"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        sql = """
        UPDATE test.hotel_mapped_url
        SET pet_attributes = %s,
            updated_at = NOW()
        WHERE id = %s;
        """
        
        cur.execute(sql, (json.dumps(pet_attributes), record_id))
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"Saved pet attributes for record ID: {record_id}")
        
    except Exception as e:
        logger.error(f"Error saving pet attributes: {e}")
        raise

def update_web_slug(record_id: int, web_slug: str):
    """Update web slug in database"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        sql = """
        UPDATE test.hotel_mapped_url
        SET web_slug = %s,
            updated_at = NOW()
        WHERE id = %s;
        """
        
        cur.execute(sql, (web_slug, record_id))
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"Updated web slug for record ID: {record_id}")
        
    except Exception as e:
        logger.error(f"Error updating web slug: {e}")
        raise

# ==================== HILTON SCRAPER ====================
class HiltonScraper:
    """Standalone Hilton scraper with Chrome version handling"""
    
    def __init__(self, headless=True):
        self.headless = headless
        self.driver_version = None

    def _make_uc_options(self):
        """Create undetected Chrome options"""
        opts = uc.ChromeOptions()
        if self.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-extensions")
        return opts

    def _get_driver(self):
        """Get Chrome driver with version handling"""
        try:
            driver = uc.Chrome(
                options=self._make_uc_options(),
                version_main=None
            )
            return driver
        except SessionNotCreatedException as e:
            logger.warning(f"Auto-detect failed: {e}")
            try:
                driver = uc.Chrome(
                    options=self._make_uc_options(),
                    version_main=144
                )
                return driver
            except Exception:
                logger.info("Trying with browser_executable_path...")
                driver = uc.Chrome(
                    options=self._make_uc_options(),
                    browser_executable_path=None
                )
                return driver

    def _click_tab(self, driver, wait, tab_id, panel_id):
        """Clicks a tab button and waits until its panel becomes visible."""
        try:
            btn = wait.until(EC.element_to_be_clickable((By.ID, tab_id)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            btn.click()
            time.sleep(0.5)
            panel = wait.until(EC.visibility_of_element_located((By.ID, panel_id)))
            return panel
        except Exception as e:
            logger.warning(f"Error clicking tab {tab_id}: {e}")
            raise

    def _parse_parking_html(self, container_el):
        """Parse parking tab content"""
        items = {}
        try:
            lis = container_el.find_elements(By.CSS_SELECTOR, "li")
            for li in lis:
                ps = li.find_elements(By.TAG_NAME, "p")
                if len(ps) >= 2:
                    label = ps[0].text.strip()
                    val = ps[1].text.strip()
                    if label:
                        items[label] = val
        except Exception as e:
            logger.warning(f"Error parsing parking: {e}")
        return items

    def _parse_pets_html(self, container_el):
        """Parse pets tab content"""
        items = {}
        try:
            lis = container_el.find_elements(By.CSS_SELECTOR, "li")
            for li in lis:
                ps = li.find_elements(By.TAG_NAME, "p")
                if len(ps) >= 2:
                    label = ps[0].text.strip()
                    val = ps[1].text.strip()
                    if label:
                        items[label] = val
        except Exception as e:
            logger.warning(f"Error parsing pets: {e}")
        return items

    def _parse_smoking_html(self, container_el):
        """Parse smoking tab content"""
        try:
            text_el = container_el.find_element(By.CSS_SELECTOR, "[data-testid='policy-smoking']")
            return text_el.text.strip()
        except NoSuchElementException:
            try:
                ps = container_el.find_elements(By.TAG_NAME, "p")
                if ps:
                    return ps[0].text.strip()
            except:
                pass
        return ""

    def _parse_wifi_html(self, container_el):
        """Parse WiFi tab content"""
        try:
            text_el = container_el.find_element(By.CSS_SELECTOR, "[data-testid='policy-wifi']")
            return text_el.text.strip()
        except NoSuchElementException:
            try:
                ps = container_el.find_elements(By.TAG_NAME, "p")
                if ps:
                    return ps[0].text.strip()
            except:
                pass
        return ""

    def _parse_amenities(self, driver):
        """Parse amenities grid"""
        try:
            selectors = [
                "[data-testid='icon-grid-header']",
                ".amenities-section",
                "[class*='amenities']",
                "h2:contains('Amenities')"
            ]
            
            for selector in selectors:
                try:
                    driver.find_element(By.CSS_SELECTOR, selector)
                    break
                except:
                    continue
            
            labels = []
            amenity_selectors = [
                "[data-testid^='grid-item-label-']",
                ".amenity-item",
                "[class*='amenity'] p",
                ".facility-item",
                "li[aria-label]"
            ]
            
            for selector in amenity_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    for el in elements:
                        text = el.text.strip()
                        if text and len(text) > 1:
                            labels.append(text)
                    if labels:
                        break
                except:
                    continue
            
            seen = set()
            out = []
            for x in labels:
                if x and x not in seen:
                    seen.add(x)
                    out.append(x)
            return out
            
        except Exception as e:
            logger.warning(f"Could not parse amenities: {e}")
            return []

    def extract_all_data(self, url: str, wait_timeout: int = 30) -> Dict[str, Any]:
        """Main method to extract all data from Hilton website."""
        driver = None
        try:
            driver = self._get_driver()
            wait = WebDriverWait(driver, wait_timeout)
            
            logger.info(f"Opening URL: {url}")
            driver.get(url)
            time.sleep(2)
            
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            time.sleep(1)
            
            # Extract hotel name
            hotel_name = ""
            try:
                name_selectors = [
                    "h1[data-testid='hotel-name']",
                    ".hotel-name",
                    "h1.property-name",
                    "[class*='hotel-name'] h1"
                ]
                for selector in name_selectors:
                    try:
                        name_element = driver.find_element(By.CSS_SELECTOR, selector)
                        hotel_name = name_element.text.strip()
                        if hotel_name:
                            break
                    except:
                        continue
            except Exception as e:
                logger.warning(f"Could not find hotel name: {e}")
            
            # Extract description
            description = ""
            try:
                desc_selectors = [
                    "[data-testid='property-description']",
                    ".property-description",
                    ".hotel-description",
                    "[class*='description'] p"
                ]
                for selector in desc_selectors:
                    try:
                        desc_element = driver.find_element(By.CSS_SELECTOR, selector)
                        description = desc_element.text.strip()
                        if description:
                            break
                    except:
                        continue
            except Exception as e:
                logger.warning(f"Could not find property description: {e}")
            
            # Extract address
            contact_info = {"address": "", "phone": ""}
            address_selectors = [
                "span.underline-offset-2.underline.inline-block", 
                "[data-testid='property-address']",
                ".property-address",
                "[itemprop='address']"
            ]

            for selector in address_selectors:
                try:
                    address_element = driver.find_element(By.CSS_SELECTOR, selector)
                    contact_info['address'] = address_element.text.strip()
                    if contact_info['address']: 
                        break
                except:
                    continue

            if not contact_info['address']:
                try:
                    xpath_selector = '//*[@id="__next"]/div[2]/div/div[1]/div[2]/a/span[1]'
                    address_element = driver.find_element(By.XPATH, xpath_selector)
                    contact_info['address'] = address_element.text.strip()
                except Exception as e:
                    logger.warning(f"Could not find address via CSS or XPath: {e}")
            
            # Extract phone
            try:
                phone_selectors = [
                    "[data-testid='property-phone']",
                    ".property-phone",
                    ".hotel-phone",
                    "[href^='tel:']"
                ]
                for selector in phone_selectors:
                    try:
                        phone_element = driver.find_element(By.CSS_SELECTOR, selector)
                        contact_info['phone'] = phone_element.text.strip()
                        break
                    except:
                        continue
            except Exception as e:
                logger.warning(f"Could not find phone: {e}")
            
            # Try to click policy tabs if they exist
            parking_policy = {}
            pets_policy = {}
            smoking_policy = ""
            wifi_policy = ""
            
            try:
                policies_section = driver.find_elements(By.CSS_SELECTOR, "[role='tablist'], .policies-section, #policies-tab-0")
                if policies_section:
                    # Parking
                    try:
                        parking_panel = self._click_tab(driver, wait, "policies-tab-0", "tab-panel-policies-tab-0")
                        parking_policy = self._parse_parking_html(parking_panel)
                    except Exception as e:
                        logger.warning(f"Could not scrape parking policy: {e}")
                    
                    # Pets
                    try:
                        pets_panel = self._click_tab(driver, wait, "policies-tab-1", "tab-panel-policies-tab-1")
                        pets_policy = self._parse_pets_html(pets_panel)
                    except Exception as e:
                        logger.warning(f"Could not scrape pets policy: {e}")
                    
                    # Smoking
                    try:
                        smoking_panel = self._click_tab(driver, wait, "policies-tab-2", "tab-panel-policies-tab-2")
                        smoking_policy = self._parse_smoking_html(smoking_panel)
                    except Exception as e:
                        logger.warning(f"Could not scrape smoking policy: {e}")
                    
                    # WiFi
                    try:
                        wifi_panel = self._click_tab(driver, wait, "policies-tab-3", "tab-panel-policies-tab-3")
                        wifi_policy = self._parse_wifi_html(wifi_panel)
                    except Exception as e:
                        logger.warning(f"Could not scrape WiFi policy: {e}")
            except Exception as e:
                logger.warning(f"Could not access policy tabs: {e}")
            
            # Extract amenities
            amenities = self._parse_amenities(driver)
            
            # Extract rating
            rating = ""
            try:
                rating_selectors = [
                    "[data-testid='review-rating']",
                    ".rating-score",
                    ".review-rating",
                    "[class*='rating'] strong"
                ]
                for selector in rating_selectors:
                    try:
                        rating_element = driver.find_element(By.CSS_SELECTOR, selector)
                        rating = rating_element.text.strip()
                        break
                    except:
                        continue
            except Exception as e:
                logger.warning(f"Could not find rating: {e}")
            
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
            logger.error(f"Error in extract_all_data: {e}")
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
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass

# ==================== ATTRIBUTE EXTRACTION MODELS ====================
T = TypeVar("T")

class ExtractionStatus(str, Enum):
    PRESENT = "present"
    EXPLICIT_NONE = "explicit_none"
    NOT_MENTIONED = "not_mentioned"

class NullableField(Generic[T], BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    status: ExtractionStatus = Field(
        description=(
            "Indicates whether the information was explicitly present, "
            "explicitly stated as none / no restriction / not applicable, "
            "or not mentioned at all in the source text"
        )
    )
    value: Optional[T] = Field(
        default=None,
        description=(
            "Extracted value if status is 'present'. "
            "Must be null if status is 'explicit_none' or 'not_mentioned'."
        )
    )

PREDEFINED_ATTRIBUTE_VALUES = {
    "allowed_species": {
        "PET_TYPE_DOG": "Dog",
        "PET_TYPE_CAT": "Cat",
        "PET_TYPE_BIRD": "Bird",
        "PET_TYPE_FISH": "Fish",
        "PET_TYPE_SMALL": "Small Pets",
        "PET_TYPE_ALL": "All Pets",
        "PET_TYPE_SERVICE": "Service Animals",
        "PET_TYPE_DOMESTIC": "Domestic Animals",
    },
    "pet_amenities_list": {
        "AMENITY_PET_BEDS": "Pet Beds",
        "AMENITY_PET_BOWLS": "Pet Bowls",
        "AMENITY_PET_TREATS": "Pet Treats",
        "AMENITY_RELIEF_AREA": "Relief Area",
        "AMENITY_PET_MENU": "Pet Menu",
        "AMENITY_PET_TOYS": "Pet Toys",
        "AMENITY_KENNEL": "Kennel",
        "AMENITY_PET_SITTING": "Pet Sitting",
        "AMENITY_DOG_WALKING": "Dog Walking",
        "AMENITY_WASTE_BAGS": "Waste Bags",
        "AMENITY_WELCOME_KIT": "Welcome Kit",
        "AMENITY_FENCED_AREA": "Fenced Area",
        "AMENITY_DOG_WASH": "Dog Wash",
        "AMENITY_TRAILS": "Trails",
    },
    "breed_restrictions": {
        "BREED_AGGRESSIVE": "Aggressive Breeds",
        "BREED_LARGE": "Large Breeds",
        "BREED_CONTACT": "Contact for Restrictions",
        "BREED_AKITA": "Akita",
        "BREED_ALASKAN_MALAMUTE": "Alaskan Malamute",
        "BREED_AMERICAN_BULLDOG": "American Bulldog",
        "BREED_PIT_BULL": "Pit Bull",
        "BREED_STAFFORDSHIRE_TERRIER": "Staffordshire Terrier",
        "BREED_BELGIAN_MALINOIS": "Belgian Malinois",
        "BREED_BENGAL": "Bengal",
        "BREED_BOXER": "Boxer",
        "BREED_MASTIFF": "Mastiff",
        "BREED_BULL_TERRIER": "Bull Terrier",
        "BREED_BULLY": "Bully",
        "BREED_CANE_CORSO": "Cane Corso",
        "BREED_CHOW_CHOW": "Chow Chow",
        "BREED_DINGO": "Dingo",
        "BREED_DOBERMAN": "Doberman",
        "BREED_DOGO_ARGENTINO": "Dogo Argentino",
        "BREED_GERMAN_SHEPHERD": "German Shepherd",
        "BREED_GREAT_DANE": "Great Dane",
        "BREED_HUSKY": "Husky",
        "BREED_MIXED": "Mixed Breed",
        "BREED_PRESA_CANARIO": "Presa Canario",
        "BREED_ROTTWEILER": "Rottweiler",
        "BREED_SAVANNAH": "Savannah",
        "BREED_ST_BERNARD": "St. Bernard",
        "BREED_WOLF": "Wolf",
    },
}

class NullableBool(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    status: ExtractionStatus
    value: Optional[bool] = None

class NullableInt(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    status: ExtractionStatus
    value: Optional[int] = None

class NullableFloat(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    status: ExtractionStatus
    value: Optional[float] = None

class NullableStr(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    status: ExtractionStatus
    value: Optional[str] = None

class NullableStringList(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    status: ExtractionStatus
    value: Optional[List[str]] = None

class HotelPetRelatedInformation(BaseModel):
    is_pet_friendly: Optional[NullableBool] = Field(
        description="Indicates if the hotel is pet-friendly. Example: True"
    )
    
    allowed_species: Optional[NullableStringList] = Field(
        default=None,
        description=(
            "List of pet species allowed at the hotel. Use standardized codes. "
            "Examples: ['PET_TYPE_DOG'], ['PET_TYPE_CAT', 'PET_TYPE_DOG'], ['PET_TYPE_SERVICE']"
        ),
    )

    has_pet_deposit: Optional[NullableBool] = Field(
        default=None,
        description="Indicates if a pet deposit is required",
    )

    pet_deposit_amount: Optional[NullableFloat] = Field(
        default=None,
        description=(
            "Exact numeric amount required for pet deposit "
            "(extract this only if has_pet_deposit is True). "
            "Example: '$100 refundable deposit' -> 100"
        ),
    )

    is_deposit_refundable: Optional[NullableBool] = Field(
        default=None,
        description=(
            "Indicates if the pet deposit is refundable "
            "(extract this only if has_pet_deposit is True)"
        ),
    )

    pet_fee_amount: Optional[NullableFloat] = Field(
        default=None,
        description=(
            "Fee charged for pets staying at the hotel which is non-refundable in USD. "
            "(extract this only if is_pet_friendly is True)"
        ),
    )

    pet_fee_variations: Optional[NullableStringList] = Field(
        default=None,
        description=(
            "Different pet fees based on size, weight, type or period. "
            "(extract this only if is_pet_friendly is True). "
            "Example: ['Small dogs: $50 per night', 'Large dogs: $75 per night', "
            "'1-4 nights: $75', '5+ nights: $125']"
        ),
    )

    pet_fee_currency: Optional[NullableStr] = Field(
        default=None,
        description=(
            "Currency of the pet fee amount. "
            "(extract this only if is_pet_friendly is True). "
            "Example: 'usd', 'eur'"
        ),
    )

    pet_fee_interval: Optional[NullableStr] = Field(
        default=None,
        description=(
            "Interval for the pet fee charged. "
            "(extract this only if is_pet_friendly is True) "
            "Example: 'per-night', 'per-stay', 'one-time'"
        ),
    )

    max_weight_lbs: Optional[NullableInt] = Field(
        default=None,
        description=(
            "Maximum weight allowed per pet in lbs. "
            "(extract this only if is_pet_friendly is True) Example: 50"
        ),
    )

    max_pets_allowed: Optional[NullableInt] = Field(
        default=None,
        description=(
            "Maximum number of pets allowed per room. "
            "(extract this only if is_pet_friendly is True) Example: 1"
        ),
    )

    breed_restrictions: Optional[NullableStringList] = Field(
        default=None,
        description=(
            "List of breeds not allowed at the hotel. Use standardized codes. "
            "Examples: ['BREED_PIT_BULL'], "
            "['BREED_ROTTWEILER', 'BREED_BULLY'], ['BREED_LARGE']"
        ),
    )

    general_pet_rules: Optional[NullableStringList] = Field(
        default=None,
        description=(
            "Summary of the hotel's pet policy except for the other specific rules. "
            "(extract this only if is_pet_friendly is True) "
            "Example: ['Pets must be leashed', "
            "'Cannot be left unattended in room', "
            "'Pets are not allowed in dining areas']"
        ),
    )

    has_pet_amenities: Optional[NullableBool] = Field(
        default=None,
        description=(
            "Indicates if the hotel offers pet amenities such as pet beds, bowls, or a pet menu"
        ),
    )

    pet_amenities_list: Optional[NullableStringList] = Field(
        default=None,
        description=(
            "List of pet amenities provided by the hotel "
            "(only if has_pet_amenities is True). "
            "Use standardized codes. "
            "Examples: ['AMENITY_PET_BEDS'], "
            "['AMENITY_PET_BOWLS', 'AMENITY_PET_TREATS'], "
            "['AMENITY_PET_MENU', 'AMENITY_DOG_WALKING']"
        ),
    )

    service_animals_allowed: Optional[NullableBool] = Field(
        default=None,
        description="Whether service animals are allowed at this property",
    )

    emotional_support_animals_allowed: Optional[NullableBool] = Field(
        default=None,
        description="Whether emotional support animals (ESA) are allowed at this property",
    )

    service_animal_policy: Optional[NullableStr] = Field(
        default=None,
        description="Service animal policy details and requirements",
    )

    minimum_pet_age: Optional[NullableInt] = Field(
        default=None,
        description="Minimum pet age requirement in months",
    )
    
    model_config = ConfigDict(
        arbitrary_types_allowed=True
    )

class HotelPetRelatedInformationConfidence(BaseModel):
    is_pet_friendly: float
    allowed_species: float
    has_pet_deposit: float
    pet_deposit_amount: float
    is_deposit_refundable: float
    pet_fee_amount: float
    pet_fee_currency: float
    pet_fee_variations: float
    pet_fee_interval: float
    max_weight_lbs: float
    max_pets_allowed: float
    breed_restrictions: float
    general_pet_rules: float
    has_pet_amenities: float
    pet_amenities_list: float
    service_animals_allowed: float
    emotional_support_animals_allowed: float
    service_animal_policy: float
    minimum_pet_age: float

class HotelPetRelatedInformationWithConfidence(BaseModel):
    pet_information: HotelPetRelatedInformation
    confidence_scores: HotelPetRelatedInformationConfidence
    
    model_config = ConfigDict(
        arbitrary_types_allowed=True
    )

def compose_system_prompt(context: str) -> str:
    def mapping(name: str):
        return " | ".join(
            f"{k}: {v}" for k, v in PREDEFINED_ATTRIBUTE_VALUES[name].items()
        )
    
    return f"""
You are an expert travel data extraction specialist.
For EACH optional field, classify it as ONE of:

present
explicit_none (explicitly stated as none / no restriction / not offered)
not_mentioned

CRITICAL:
Silence → not_mentioned
"No restrictions", "None", "Not applicable" → explicit_none
Do NOT infer missing information
Each NullableField MUST include a status

PREDEFINED VALUE MAPPINGS:
allowed_species:
{mapping("allowed_species")}

pet_amenities_list:
{mapping("pet_amenities_list")}

breed_restrictions:
{mapping("breed_restrictions")}

NUMERIC RULES:
Convert kg to lbs (1 kg = 2.20462 lbs)
Extract numeric values only

CONFIDENCE:
Provide confidence scores between 0.0 and 1.0

SERVICE ANIMAL LOGIC (CRITICAL):
Service animals are NOT considered pets.
A property that allows ONLY service animals is NOT pet-friendly.

Set fields as follows:

If the context says "Service animals only", "Only service animals allowed",
or "No pets except service animals":
is_pet_friendly = False
service_animals_allowed = present → True
allowed_species = not_mentioned
pet_fee_amount = not_mentioned
pet_fee_variations = not_mentioned
pet_amenities_list = not_mentioned

If the context says "Pets allowed" AND mentions service animals:
is_pet_friendly = True
service_animals_allowed = present → True

If the context explicitly states "No pets allowed" BUT allows service animals:
is_pet_friendly = False
service_animals_allowed = present → True

If service animals are not mentioned at all:
service_animals_allowed = not_mentioned

IMPORTANT:
Do NOT infer pet-friendliness from service animal allowances.
Do NOT treat service animals as pets for any pet fee, deposit, or amenity fields.

HOTEL INFORMATION:
{context}

Return structured JSON strictly matching the schema.
""".strip()

# ==================== HOTEL EXTRACTION PIPELINE ====================
class HotelExtractionPipeline:
    """Complete hotel extraction pipeline with context, attributes, and slug generation"""
    
    def __init__(self):
        self.client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url="https://openrouter.ai/api/v1"
        )
        self.scraper = HiltonScraper(headless=False)
        
        # Initialize Gemini client if configured
        self.gemini_client = None
        if GEMINI_CONFIG["project_id"] and GEMINI_CONFIG["location"]:
            self.gemini_client = Client(
                vertexai=True,
                project=GEMINI_CONFIG["project_id"],
                location=GEMINI_CONFIG["location"],
            )
    
    def generate_web_context(self, prompt: str) -> str:
        """Generate web context using OpenAI"""
        try:
            response = self.client.chat.completions.create(
                model=MODEL_ID,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a strict hotel data formatter. Do NOT hallucinate."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0,
                max_tokens=1200
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Error generating web context: {e}")
            return f"Error: Could not generate web context. {str(e)}"
    
    def build_prompt(self, data: dict) -> str:
        """Build prompt for web context generation"""
        # Format parking policy
        parking_policy_str = ""
        if isinstance(data.get('parking_policy'), dict) and data['parking_policy']:
            parking_items = []
            for key, value in data['parking_policy'].items():
                parking_items.append(f"{key}: {value}")
            parking_policy_str = "\n".join(parking_items)
        else:
            parking_policy_str = "Not specified"
        
        # Format pets policy
        pets_policy_str = ""
        if isinstance(data.get('pets_policy'), dict) and data['pets_policy']:
            pets_items = []
            for key, value in data['pets_policy'].items():
                pets_items.append(f"{key}: {value}")
            pets_policy_str = "\n".join(pets_items)
        else:
            pets_policy_str = "Not specified"
        
        # Format amenities
        amenities_str = ", ".join(data.get('amenities', [])) if data.get('amenities') else "Not available"
        
        return f"""
        You are generating a hotel web_context.

        Use ONLY the data provided below.
        Do NOT hallucinate.

        Focus strongly on:
        1. Amenities & Facilities
        2. PET POLICY (fees, weight, limits)
        3. Room & stay experience
        4. Parking, WiFi, Smoking policy
        5. Location & nearby attractions

        Formatting Rules:
        - Attribute: Value
        - If pets_policy exists → clearly say:
        "# This hotel is pet-friendly and allows pets."

        HOTEL DATA:
        Hotel Name: {data.get('hotel_name', 'Unknown')}
        Description: {data.get('description', 'No description available')}
        Amenities: {amenities_str}
        Address: {data.get('contact_info', {}).get('address', 'Address not available')}
        Phone: {data.get('contact_info', {}).get('phone', 'Phone not available')}
        Rating: {data.get('rating', 'Not rated')}

        Parking Policy: {parking_policy_str}
        Pets Policy: {pets_policy_str}
        Smoking Policy: {data.get('smoking_policy', 'Not specified')}
        WiFi Policy: {data.get('wifi_policy', 'Not specified')}
        URL: {data.get('url', 'Unknown URL')}
        """
    
    def extract_pet_attributes(self, web_context: str) -> Dict[str, Any]:
        """Extract pet attributes using Gemini"""
        if not self.gemini_client:
            logger.warning("Gemini client not configured, skipping attribute extraction")
            return {}
        
        try:
            system_prompt = compose_system_prompt(web_context)
            
            config = GenerateContentConfig(
                temperature=0,
                top_p=0.8,
                response_mime_type="application/json",
                response_schema=HotelPetRelatedInformationWithConfidence,
            )
            
            response = self.gemini_client.models.generate_content(
                model="gemini-2.5-pro",
                contents=[Part.from_text(text=system_prompt)],
                config=config,
            )
            
            if response.parsed is None:
                raise ValueError("Failed to parse structured response")
            
            result = cast(HotelPetRelatedInformationWithConfidence, response.parsed)
            
            # Convert to dictionary
            return result.model_dump()
            
        except Exception as e:
            logger.error(f"Error extracting pet attributes: {e}")
            return {}
    
    def extract_hotel(self, url: str) -> Dict[str, Any]:
        """
        Complete hotel extraction pipeline
        
        Steps:
        1. Scrape raw data from hotel URL
        2. Generate hash of raw content
        3. Save raw data to database
        4. Generate web context using LLM
        5. Save web context to database
        6. Extract pet attributes using Gemini
        7. Save pet attributes to database
        8. Generate web slug
        9. Update database with slug
        10. Return all extracted data
        """
        try:
            logger.info(f"Starting extraction pipeline for URL: {url}")
            
            # Step 1: Scrape raw data
            logger.info("Step 1: Scraping hotel page...")
            hotel_data = self.scraper.extract_all_data(url)
            
            # Create raw content string for hashing
            raw_content_parts = [
                hotel_data.get('hotel_name', ''),
                hotel_data.get('description', ''),
                hotel_data.get('contact_info', {}).get('address', ''),
                hotel_data.get('contact_info', {}).get('phone', ''),
                ', '.join(hotel_data.get('amenities', [])),
                str(hotel_data.get('parking_policy', {})),
                str(hotel_data.get('pets_policy', {})),
                hotel_data.get('smoking_policy', ''),
                hotel_data.get('wifi_policy', ''),
                hotel_data.get('rating', ''),
            ]
            raw_content = ' '.join(raw_content_parts)
            
            # Step 2: Generate hash
            logger.info("Step 2: Generating content hash...")
            hash_value = _hash_context(raw_content)
            
            # Step 3: Parse address
            address_info = parse_address(hotel_data.get('contact_info', {}).get('address', ''))
            
            # Step 4: Save raw extraction to database
            logger.info("Step 3: Saving raw extraction to database...")
            record_id = save_raw_extraction(
                url=url,
                raw_content=raw_content,
                hash_value=hash_value,
                hotel_name=hotel_data.get('hotel_name', ''),
                address=hotel_data.get('contact_info', {}).get('address', '')
            )
            
            # Step 5: Generate web context
            logger.info("Step 4: Generating web context...")
            prompt = self.build_prompt(hotel_data)
            web_context = self.generate_web_context(prompt)
            
            # Step 6: Save web context to database
            logger.info("Step 5: Saving web context to database...")
            save_web_context(record_id, web_context)
            
            # Step 7: Extract pet attributes using Gemini
            logger.info("Step 6: Extracting pet attributes...")
            pet_attributes = self.extract_pet_attributes(web_context)
            
            # Step 8: Save pet attributes to database
            logger.info("Step 7: Saving pet attributes to database...")
            save_pet_attributes(record_id, pet_attributes)
            
            # Step 9: Generate web slug
            logger.info("Step 8: Generating web slug...")
            web_slug = generate_combined_slug(
                country_code=address_info.get('country_code', 'US'),
                state_code=address_info.get('state', ''),
                city=address_info.get('city', ''),
                hotel_name=hotel_data.get('hotel_name', ''),
                address_line_1=address_info.get('address_line_1', '')
            )
            
            # Step 10: Update database with slug
            logger.info("Step 9: Updating database with slug...")
            if web_slug:
                update_web_slug(record_id, web_slug)
            
            # Return complete result
            result = {
                "status": "success",
                "record_id": record_id,
                "hash": hash_value,
                "hotel_data": hotel_data,
                "address_info": address_info,
                "web_context": web_context,
                "pet_attributes": pet_attributes,
                "web_slug": web_slug,
                "url": url
            }
            
            logger.info(f"Extraction completed successfully for {url}")
            return result
            
        except Exception as e:
            logger.error(f"Error in extraction pipeline: {e}", exc_info=True)
            return {
                "status": "error",
                "message": str(e),
                "url": url
            }