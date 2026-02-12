# hilton_extraction.py
import logging
from typing import Dict, Any, Optional

from config import Config
from scraping.hilton_scraper import HiltonScraper
from db.operations import HotelDatabaseOperations
from processors.context_processor import ContextProcessor
from processors.attribute_processor import AttributeProcessor
from processors.slug_processor import SlugProcessor
from utils.context_hashing import ContextHasher

from utils.context_hashing import cont
from utils.address_parser import AddressParser

logger = logging.getLogger(__name__)

class HotelExtractionPipeline:
    """Main orchestration class for hotel extraction pipeline"""
    
    def __init__(self, config: Config = None):
        self.config = config or Config()
        
        # Initialize components
        self.scraper = HiltonScraper(headless=self.config.extraction.headless)
        self.db_ops = HotelDatabaseOperations(self.config.db)
        self.context_processor = ContextProcessor(self.config.api)
        self.attribute_processor = AttributeProcessor(self.config.api)
        self.slug_processor = SlugProcessor()
        self.hasher = ContextHasher()
        self.address_parser = AddressParser()
    
    def extract_hotel(self, url: str, skip_existing: bool = True) -> Dict[str, Any]:
        """
        Complete hotel extraction pipeline
        
        Args:
            url: Hotel URL to extract
            skip_existing: Skip if URL already exists in database
            
        Returns:
            Dictionary containing extraction results
        """
        try:
            logger.info(f"Starting extraction pipeline for URL: {url}")
            
            # Check if URL already exists
            if skip_existing:
                existing = self.db_ops.get_existing_record(url)
                if existing:
                    logger.info(f"URL already exists in database: {url}")
                    return {
                        "status": "skipped",
                        "message": "URL already exists",
                        "record_id": existing.get('id'),
                        "url": url
                    }
            
            # Step 1: Scrape raw data
            logger.info("Step 1: Scraping hotel page...")
            hotel_data = self.scraper.extract_all_data(url)
            
            if not hotel_data.get('hotel_name'):
                raise ValueError("Failed to extract hotel data")
            
            # Step 2: Generate hash
            logger.info("Step 2: Generating content hash...")
            hash_value = self.hasher.hash_hotel_data(hotel_data)
            
            # Step 3: Parse address
            logger.info("Step 3: Parsing address...")
            address_info = self.address_parser.parse_address(
                hotel_data.get('contact_info', {}).get('address', '')
            )
            
            # Step 4: Save raw extraction to database
            logger.info("Step 4: Saving raw extraction to database...")
            record_id = self.db_ops.save_raw_extraction(
                url=url,
                raw_content=str(hotel_data),  # Simplified
                hash_value=hash_value,
                hotel_name=hotel_data.get('hotel_name', ''),
                address_info=address_info
            )
            
            # Step 5: Generate web context
            logger.info("Step 5: Generating web context...")
            prompt = self.context_processor.build_prompt(hotel_data)
            web_context = self.context_processor.generate_web_context(prompt)
            
            # Step 6: Save web context to database
            logger.info("Step 6: Saving web context to database...")
            self.db_ops.save_web_context(record_id, web_context)
            
            # Step 7: Extract pet attributes
            logger.info("Step 7: Extracting pet attributes...")
            pet_attributes = self.attribute_processor.extract_pet_attributes(web_context)
            
            # Step 8: Save pet attributes to database
            logger.info("Step 8: Saving pet attributes to database...")
            self.db_ops.save_pet_attributes(record_id, pet_attributes)
            
            # Step 9: Generate web slug
            logger.info("Step 9: Generating web slug...")
            web_slug = self.slug_processor.generate_from_hotel_data(
                hotel_data, 
                address_info
            )
            
            # Step 10: Update database with slug
            logger.info("Step 10: Updating database with slug...")
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
    
    def batch_extract(self, urls: list, skip_existing: bool = True) -> list:
        """Extract multiple hotels"""
        results = []
        for url in urls:
            try:
                result = self.extract_hotel(url, skip_existing)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to extract {url}: {e}")
                results.append({
                    "status": "error",
                    "message": str(e),
                    "url": url
                })
        return results

# Usage example
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create pipeline
    pipeline = HotelExtractionPipeline()
    
    # Extract single hotel
    result = pipeline.extract_hotel(
        url="https://www.hilton.com/en/hotels/phxhiti-tempe-arizona/"
    )
    
    # Or extract multiple
    urls = [
        "https://www.hilton.com/en/hotels/phxhiti-tempe-arizona/",
        "https://www.hilton.com/en/hotels/phxazhx-hilton-phoenix-airport/"
    ]
    
    results = pipeline.batch_extract(urls)