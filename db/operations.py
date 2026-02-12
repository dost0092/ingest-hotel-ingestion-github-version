"""
Database operations for hotel extraction
"""
import logging
import json
from typing import Dict, Any, Optional, Tuple

from db.db_connection import get_db_cursor
from db.queries import (
    RAW_EXTRACTION_INSERT,
    WEB_CONTEXT_UPDATE,
    PET_ATTRIBUTES_UPDATE,
    WEB_SLUG_UPDATE,
    CHECK_URL_EXISTS
)
from utils.address_parser import parse_address

logger = logging.getLogger(__name__)

class HotelDatabaseOperations:
    """Database operations for hotel extraction pipeline"""
    
    @staticmethod
    def save_raw_extraction(
        url: str, 
        raw_content: str, 
        hash_value: str, 
        hotel_name: str = "", 
        address: str = ""
    ) -> int:
        """
        Save raw extraction to database and return the ID
        """
        try:
            # Parse address if available
            address_info = parse_address(address) if address else {}
            
            with get_db_cursor() as cur:
                cur.execute(RAW_EXTRACTION_INSERT, (
                    url,
                    hotel_name,
                    address_info.get("city", ""),
                    address_info.get("state", ""),
                    address_info.get("country", ""),
                    address_info.get("country_code", "US"),
                    address_info.get("address_line_1", ""),
                    hash_value
                ))
                
                record_id = cur.fetchone()[0]
                logger.info(f"Saved raw extraction for {url} with ID: {record_id}")
                return record_id
                
        except Exception as e:
            logger.error(f"Error saving raw extraction: {e}")
            raise
    
    @staticmethod
    def save_web_context(record_id: int, web_context: str) -> None:
        """Save web context to database"""
        try:
            with get_db_cursor() as cur:
                cur.execute(WEB_CONTEXT_UPDATE, (web_context, record_id))
                logger.info(f"Saved web context for record ID: {record_id}")
                
        except Exception as e:
            logger.error(f"Error saving web context: {e}")
            raise
    
    @staticmethod
    def save_pet_attributes(record_id: int, pet_attributes: Dict[str, Any]) -> None:
        """Save pet attributes as JSONB"""
        try:
            with get_db_cursor() as cur:
                cur.execute(PET_ATTRIBUTES_UPDATE, (json.dumps(pet_attributes), record_id))
                logger.info(f"Saved pet attributes for record ID: {record_id}")
                
        except Exception as e:
            logger.error(f"Error saving pet attributes: {e}")
            raise
    
    @staticmethod
    def update_web_slug(record_id: int, web_slug: str) -> None:
        """Update web slug in database"""
        try:
            with get_db_cursor() as cur:
                cur.execute(WEB_SLUG_UPDATE, (web_slug, record_id))
                logger.info(f"Updated web slug for record ID: {record_id}")
                
        except Exception as e:
            logger.error(f"Error updating web slug: {e}")
            raise
    
    @staticmethod
    def check_url_exists(url: str) -> Optional[Tuple[int, str]]:
        """Check if URL already exists in database"""
        try:
            with get_db_cursor() as cur:
                cur.execute(CHECK_URL_EXISTS, (url,))
                result = cur.fetchone()
                if result:
                    return result  # (id, hash_value)
                return None
        except Exception as e:
            logger.error(f"Error checking URL existence: {e}")
            return None