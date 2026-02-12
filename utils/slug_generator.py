"""
Slug generation utilities
"""
import re
import unicodedata
from typing import Optional

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
    # Remove special characters (#, ., ', etc.) and keep only alphanumeric
    val = re.sub(r"[^a-z0-9]", "", val)
    return val

def generate_combined_slug(
    country_code: str, 
    state_code: str, 
    city: str, 
    hotel_name: str, 
    address_line_1: str
) -> Optional[str]:
    """Generate slug from all components: country-state-city-name-address_line_1"""
    if not state_code or not state_code.strip():
        return None
    if not address_line_1 or not address_line_1.strip():
        return None
    
    # Normalize each component
    country_norm = normalize_address_slug(country_code)
    state_norm = normalize_address_slug(state_code)
    city_norm = normalize_address_slug(city)
    name_norm = normalize_address_slug(hotel_name)
    address_norm = normalize_address_slug(address_line_1)
    
    # Combine in the specified format: country-state-city-name-address_line_1
    parts = [country_norm, state_norm, city_norm, name_norm, address_norm]
    parts = [p for p in parts if p]
    
    # Join with hyphens
    slug = "-".join(parts)
    return slug