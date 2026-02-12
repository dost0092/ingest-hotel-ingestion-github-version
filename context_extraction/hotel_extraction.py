"""
Hotel Extraction Pipeline - Main orchestration
"""
import logging
from typing import Dict, Any

from scraping.hilton_scraper import HiltonScraper
from db.operations import HotelDatabaseOperations
from llm.web_context_generator import WebContextGenerator
from llm.pet_attribute_extractor import PetAttributeExtractor
from utils.slug_generator import generate_combined_slug
from utils.context_hashing import generate_raw_content_hash
from utils.address_parser import parse_address
from scraping.hyatt_scraper import HyattScraper
from utils.support_functions import detect_hotel_chain_from_url

logger = logging.getLogger(__name__)

class HotelExtractionPipeline:
    """Complete hotel extraction pipeline with context, attributes, and slug generation"""
    
    def __init__(self):
        self.scraper = None
        self.db_ops = HotelDatabaseOperations()
        self.web_context_gen = WebContextGenerator()
        self.pet_attr_extractor = PetAttributeExtractor()
    
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
            
            # Step 1: Check if URL already exists
            existing_record = self.db_ops.check_url_exists(url)
            if existing_record:
                logger.info(f"URL already exists in database: {url}")
                return {
                    "status": "exists",
                    "message": "URL already extracted",
                    "record_id": existing_record[0],
                    "hash": existing_record[1]
                }
            
            # Step 2: Scrape raw data
            # Step 1: Detect hotel chain
            chain = detect_hotel_chain_from_url(url)

            if chain == "hilton":
                self.scraper = HiltonScraper(headless=True)
            elif chain == "hyatt":
                self.scraper = HyattScraper(headless=True)
            else:
                raise ValueError(f"Unsupported hotel chain detected: {chain}")

            logger.info(f"Detected chain: {chain}")

            # Step 2: Scrape raw data
            logger.info("Step 1: Scraping hotel page...")
            hotel_data = self.scraper.extract_all_data(url)
            
            # Step 3: Generate hash
            logger.info("Step 2: Generating content hash...")
            hash_value = generate_raw_content_hash(hotel_data)
            
            # Step 4: Parse address
            address_info = parse_address(hotel_data.get('contact_info', {}).get('address', ''))
            
            # Step 5: Save raw extraction to database
            logger.info("Step 3: Saving raw extraction to database...")
            record_id = self.db_ops.save_raw_extraction(
                url=url,
                raw_content=' '.join([
                    hotel_data.get('hotel_name', ''),
                    hotel_data.get('description', ''),
                    hotel_data.get('contact_info', {}).get('address', ''),
                ]),
                hash_value=hash_value,
                hotel_name=hotel_data.get('hotel_name', ''),
                address=hotel_data.get('contact_info', {}).get('address', '')
            )
            
            # Step 6: Generate web context
            logger.info("Step 4: Generating web context...")
            web_context = self.web_context_gen.generate(hotel_data)
            
            # Step 7: Save web context to database
            logger.info("Step 5: Saving web context to database...")
            self.db_ops.save_web_context(record_id, web_context)
            
            # Step 8: Extract pet attributes using Gemini
            logger.info("Step 6: Extracting pet attributes...")
            pet_attributes = self.pet_attr_extractor.extract(web_context)
            
            # Step 9: Save pet attributes to database
            logger.info("Step 7: Saving pet attributes to database...")
            if pet_attributes:  # Only save if we have attributes
                self.db_ops.save_pet_attributes(record_id, pet_attributes)
            
            # Step 10: Generate web slug
            logger.info("Step 8: Generating web slug...")
            web_slug = generate_combined_slug(
                country_code=address_info.get('country_code', 'US'),
                state_code=address_info.get('state_code', ''),
                city=address_info.get('city', ''),
                hotel_name=hotel_data.get('hotel_name', ''),
                address_line_1=address_info.get('address_line_1', '')
            )
            
            # Step 11: Update database with slug
            logger.info("Step 9: Updating database with slug...")
            if web_slug:
                self.db_ops.update_web_slug(record_id, web_slug)
            
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