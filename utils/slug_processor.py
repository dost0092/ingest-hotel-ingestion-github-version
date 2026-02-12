# processors/slug_processor.py
import re
import unicodedata
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class SlugProcessor:
    """Handles slug generation from hotel data"""
    
    @staticmethod
    def remove_accents(text: str) -> str:
        """Remove accents from characters (é → e, ñ → n, etc.)"""
        if not text:
            return ""
        nfd = unicodedata.normalize('NFD', text)
        return ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')
    
    @staticmethod
    def normalize_address_slug(address: str) -> str:
        """Normalize address for slug generation"""
        if not address:
            return ""
        
        val = str(address).strip()
        val = SlugProcessor.remove_accents(val)
        val = val.lower()
        val = re.sub(r"[^a-z0-9]", "", val)
        return val
    
    def generate_combined_slug(self, country_code: str, state_code: str, city: str,
                              hotel_name: str, address_line_1: str) -> Optional[str]:
        """Generate slug from all components"""
        if not state_code or not state_code.strip():
            return None
        if not address_line_1 or not address_line_1.strip():
            return None
        
        country_norm = self.normalize_address_slug(country_code)
        state_norm = self.normalize_address_slug(state_code)
        city_norm = self.normalize_address_slug(city)
        name_norm = self.normalize_address_slug(hotel_name)
        address_norm = self.normalize_address_slug(address_line_1)
        
        parts = [country_norm, state_norm, city_norm, name_norm, address_norm]
        parts = [p for p in parts if p]
        
        slug = "-".join(parts)
        return slug
    
    def generate_from_hotel_data(self, hotel_data: dict, address_info: dict) -> Optional[str]:
        """Generate slug from hotel data dictionary"""
        return self.generate_combined_slug(
            country_code=address_info.get('country_code', 'US'),
            state_code=address_info.get('state', ''),
            city=address_info.get('city', ''),
            hotel_name=hotel_data.get('hotel_name', ''),
            address_line_1=address_info.get('address_line_1', '')
        )