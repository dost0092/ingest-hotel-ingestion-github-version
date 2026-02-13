"""
Hotel Scraper API - Production Version
Supports Hilton + Hyatt
GCP VM Ready (Headless)
"""

import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, HttpUrl
from dotenv import load_dotenv

# ---------------------------------------------------------
# ENV + LOGGING
# ---------------------------------------------------------

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# IMPORT SCRAPERS
# ---------------------------------------------------------

from url.hilton_location_scraper import HiltonLocationsScraper
from url.hyatt_location_scraper import HyattPetFriendlyScraper
from scraping.hilton_scraper import HiltonScraper
from scraping.hyatt_scraper import HyattScraper
from scraping.marriot_scraper import MarriottScraper
from utils.support_functions import detect_hotel_chain_from_url

# Optional modular imports
from llm.web_context_generator import WebContextGenerator
from llm.pet_attribute_extractor import PetAttributeExtractor
from utils.slug_generator import generate_combined_slug
from utils.address_parser import parse_address
from utils.context_hashing import generate_raw_content_hash
from context_extraction.hotel_extraction import HotelExtractionPipeline

# ---------------------------------------------------------
# FASTAPI INIT
# ---------------------------------------------------------

app = FastAPI(
    title="Hotel Scraper API",
    version="2.1.0",
)

active_scrapes: Dict[str, Dict[str, Any]] = {}

# ---------------------------------------------------------
# MODELS
# ---------------------------------------------------------

class ScrapeRequest(BaseModel):
    hotel_chain: str = "hilton"
    country_code: Optional[str] = None


class ScrapeResponse(BaseModel):
    status: str
    message: str
    session_id: Optional[str] = None


class HotelExtractionRequest(BaseModel):
    url: HttpUrl
    save_to_db: bool = True
    extract_attributes: bool = True


class HotelExtractionResponse(BaseModel):
    status: str
    message: str
    data: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None


# ---------------------------------------------------------
# LOCATION SCRAPER BACKGROUND TASK
# ---------------------------------------------------------

def run_scraper_task(hotel_chain: str, country_code: Optional[str], session_id: str):

    try:
        active_scrapes[session_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "hotel_chain": hotel_chain,
            "country_code": country_code,
            "type": "location_scrape"
        }

        if hotel_chain == "hilton" or hotel_chain == "Hilton":
            scraper = HiltonLocationsScraper()
            stats = scraper.scrape_all_locations(country_code_filter=country_code)

        elif hotel_chain == "hyatt" or hotel_chain == "Hyatt":
            scraper = HyattPetFriendlyScraper()
            scraper.scrape()
            stats = {"message": "Hyatt scrape completed"}
        else:
            raise ValueError("Unsupported hotel chain")

        active_scrapes[session_id].update({
            "status": "completed",
            "completed_at": datetime.now().isoformat(),
            "stats": stats
        })

    except Exception as e:
        logger.exception("Scraper error")
        active_scrapes[session_id] = {
            "status": "failed",
            "error": str(e),
            "completed_at": datetime.now().isoformat()
        }


# ---------------------------------------------------------
# HOTEL EXTRACTION BACKGROUND TASK
# ---------------------------------------------------------

def run_hotel_extraction_task(url: str, save_to_db: bool, extract_attributes: bool, session_id: str):

    try:
        chain = detect_hotel_chain_from_url(url)

        active_scrapes[session_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "url": url,
            "chain": chain,
            "type": "hotel_extraction"
        }

        if save_to_db:
            pipeline = HotelExtractionPipeline()
            result = pipeline.extract_hotel(url)

        else:
            if chain == "hilton":
                scraper = HiltonScraper(headless=True)
            elif chain == "marriott":
                scraper = MarriottScraper(headless=True)
            else:
                scraper = HyattScraper(headless=True)

            hotel_data = scraper.extract_all_data(url)

            web_context = WebContextGenerator().generate(hotel_data)
            address_info = parse_address(
                hotel_data.get("contact_info", {}).get("address", "")
            )

            web_slug = generate_combined_slug(
                country_code=address_info.get("country_code", "US"),
                state_code=address_info.get("state", ""),
                city=address_info.get("city", ""),
                hotel_name=hotel_data.get("hotel_name", ""),
                address_line_1=address_info.get("address_line_1", "")
            )

            pet_attributes = {}
            if extract_attributes:
                pet_attributes = PetAttributeExtractor().extract(web_context)

            hash_value = generate_raw_content_hash(hotel_data)

            result = {
                "hotel_data": hotel_data,
                "web_context": web_context,
                "address_info": address_info,
                "web_slug": web_slug,
                "pet_attributes": pet_attributes,
                "hash": hash_value,
                "chain": chain,
                "url": url
            }

        active_scrapes[session_id].update({
            "status": "completed",
            "completed_at": datetime.now().isoformat(),
            "result": result
        })

    except Exception as e:
        logger.exception("Extraction error")
        active_scrapes[session_id] = {
            "status": "failed",
            "error": str(e),
            "completed_at": datetime.now().isoformat()
        }


# ---------------------------------------------------------
# ENDPOINTS
# ---------------------------------------------------------

@app.get("/")
async def root():
    return {"message": "Hotel Scraper API", "version": "2.1.0"}


@app.post("/scrape_url", response_model=ScrapeResponse)
async def scrape_url(request: ScrapeRequest, background_tasks: BackgroundTasks):

    hotel_chain = request.hotel_chain.lower()

    if hotel_chain not in ["hilton", "hyatt"]:
        raise HTTPException(status_code=400, detail="Invalid hotel_chain")

    session_id = f"{hotel_chain}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    background_tasks.add_task(
        run_scraper_task,
        hotel_chain,
        request.country_code,
        session_id
    )

    return ScrapeResponse(
        status="started",
        message=f"{hotel_chain} scraping started",
        session_id=session_id
    )


@app.post("/scrape_hotel", response_model=HotelExtractionResponse)
async def scrape_hotel(
    request: HotelExtractionRequest,
    background_tasks: BackgroundTasks,
    synchronous: bool = Query(False)
):

    session_id = f"extract_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    url = str(request.url)

    if synchronous:
        try:
            run_hotel_extraction_task(
                url,
                request.save_to_db,
                request.extract_attributes,
                session_id
            )

            return HotelExtractionResponse(
                status="completed",
                message="Extraction completed",
                data=active_scrapes[session_id].get("result"),
                session_id=session_id
            )

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    else:
        background_tasks.add_task(
            run_hotel_extraction_task,
            url,
            request.save_to_db,
            request.extract_attributes,
            session_id
        )

        return HotelExtractionResponse(
            status="queued",
            message="Extraction queued",
            session_id=session_id
        )


@app.get("/scrape/status/{session_id}")
async def get_status(session_id: str):
    if session_id not in active_scrapes:
        raise HTTPException(status_code=404, detail="Session not found")
    return active_scrapes[session_id]


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "active_jobs": len(active_scrapes),
        "timestamp": datetime.now().isoformat()
    }


# ---------------------------------------------------------
# GCP VM ENTRYPOINT
# ---------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
