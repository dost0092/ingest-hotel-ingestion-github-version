"""
Web context generation using LLM
"""
import logging
from typing import Dict, Any

from openai import OpenAI
from config.settings import OPENAI_API_KEY, MODEL_ID

logger = logging.getLogger(__name__)


class WebContextGenerator:
    def __init__(self):
        self.client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "HTTP-Referer": "https://yourdomain.com",   # required (can be localhost)
                "X-Title": "Hotel Web Context Generator"    # required
            }
        )
    
    def build_prompt(self, data: Dict[str, Any]) -> str:
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
    
    def generate(self, data: Dict[str, Any]) -> str:
        """Generate web context using OpenAI"""
        try:
            prompt = self.build_prompt(data)
            
            response = self.client.chat.completions.create(
                model=MODEL_ID,
                messages=[
                    {"role": "system", "content": "You are a strict hotel data formatter. Do NOT hallucinate."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=1200
            )
            
            web_context = response.choices[0].message.content.strip()
            print(web_context)
            logger.info("Web context generated successfully")
            return web_context
            
        except Exception as e:
            logger.error(f"Error generating web context: {e}")
            return f"Error: Could not generate web context. {str(e)}"