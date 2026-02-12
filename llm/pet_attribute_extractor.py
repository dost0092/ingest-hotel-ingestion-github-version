import logging
import json
from typing import Dict, Any, cast

# Keep Gemini imports but they will be unused in the logic below
# from google.genai import Client
# from google.genai.types import GenerateContentConfig, Part

# OpenRouter / OpenAI
from openai import OpenAI

from config.settings import GEMINI_CONFIG, OPENAI_API_KEY
from llm.models import (
    HotelPetRelatedInformationWithConfidence,
    PREDEFINED_ATTRIBUTE_VALUES,
    NullableBool,
    NullableStringList,
    NullableFloat,
    NullableInt,
    NullableStr,
    ExtractionStatus
)

logger = logging.getLogger(__name__)


class PetAttributeExtractor:
    """Extract pet attributes using OpenRouter (Debugging) instead of Gemini API"""

    def __init__(self):
        # --- GEMINI CLIENT (COMMENTED OUT - DO NOT TOUCH) ---
        # self.client = None
        # if GEMINI_CONFIG.get("project_id") and GEMINI_CONFIG.get("location"):
        #     self.client = Client(
        #         vertexai=True,
        #         project=GEMINI_CONFIG["project_id"],
        #         location=GEMINI_CONFIG["location"],
        #     )

        # --- OPENAI / OPENROUTER CLIENT (ACTIVE) ---
        self.client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "HTTP-Referer": "https://yourdomain.com",   # required
                "X-Title": "Hotel Pet Attributes Generator"    # required
            }
        )

    def compose_system_prompt(self, context: str) -> str:
        """Compose system prompt for pet attribute extraction"""

        def mapping(name: str):
            return " | ".join(
                f"{k}: {v}" for k, v in PREDEFINED_ATTRIBUTE_VALUES[name].items()
            )

        return f"""
You are an expert travel data extraction specialist.

You MUST return a JSON object with TWO top-level keys:
1. "pet_information" - containing all extracted pet policy fields
2. "confidence_scores" - containing confidence values (0.0 to 1.0) for each field

For EACH optional field in pet_information, classify it as ONE of:
- present
- explicit_none (explicitly stated as none / no restriction / not offered)
- not_mentioned

CRITICAL:
- Silence → not_mentioned
- "No restrictions", "None", "Not applicable" → explicit_none
- Do NOT infer missing information
- Each NullableField MUST include a status

PREDEFINED VALUE MAPPINGS:

allowed_species:
{mapping("allowed_species")}

pet_amenities_list:
{mapping("pet_amenities_list")}

breed_restrictions:
{mapping("breed_restrictions")}

NUMERIC RULES:
- Convert kg to lbs (1 kg = 2.20462 lbs)
- Extract numeric values only

SERVICE ANIMAL LOGIC (CRITICAL):
- Service animals are NOT considered pets.
- A property that allows ONLY service animals is NOT pet-friendly.

Set fields as follows:

If the context says "Service animals only", "Only service animals allowed",
or "No pets except service animals":
- is_pet_friendly = {{"status": "present", "value": false}}
- service_animals_allowed = {{"status": "present", "value": true}}
- allowed_species = {{"status": "not_mentioned"}}
- pet_fee_amount = {{"status": "not_mentioned"}}
- pet_fee_variations = {{"status": "not_mentioned"}}
- pet_amenities_list = {{"status": "not_mentioned"}}

If the context says "Pets allowed" AND mentions service animals:
- is_pet_friendly = {{"status": "present", "value": true}}
- service_animals_allowed = {{"status": "present", "value": true}}

If the context explicitly states "No pets allowed" BUT allows service animals:
- is_pet_friendly = {{"status": "present", "value": false}}
- service_animals_allowed = {{"status": "present", "value": true}}

If service animals are not mentioned at all:
- service_animals_allowed = {{"status": "not_mentioned"}}

IMPORTANT:
- Do NOT infer pet-friendliness from service animal allowances.
- Do NOT treat service animals as pets for any pet fee, deposit, or amenity fields.

RESPONSE FORMAT EXAMPLE:
{{
  "pet_information": {{
    "is_pet_friendly": {{"status": "present", "value": true}},
    "allowed_species": {{"status": "present", "value": ["PET_TYPE_DOG", "PET_TYPE_CAT"]}},
    "has_pet_deposit": {{"status": "present", "value": true}},
    "pet_deposit_amount": {{"status": "present", "value": 75.0}},
    "is_deposit_refundable": {{"status": "present", "value": false}},
    "pet_fee_amount": {{"status": "not_mentioned"}},
    "pet_fee_variations": {{"status": "present", "value": ["1-4 nights: $75", "5+ nights: $125"]}},
    "pet_fee_currency": {{"status": "present", "value": "usd"}},
    "pet_fee_interval": {{"status": "present", "value": "per-stay"}},
    "max_weight_lbs": {{"status": "not_mentioned"}},
    "max_pets_allowed": {{"status": "not_mentioned"}},
    "breed_restrictions": {{"status": "not_mentioned"}},
    "general_pet_rules": {{"status": "not_mentioned"}},
    "has_pet_amenities": {{"status": "not_mentioned"}},
    "pet_amenities_list": {{"status": "not_mentioned"}},
    "service_animals_allowed": {{"status": "not_mentioned"}},
    "emotional_support_animals_allowed": {{"status": "not_mentioned"}},
    "service_animal_policy": {{"status": "not_mentioned"}},
    "minimum_pet_age": {{"status": "not_mentioned"}}
  }},
  "confidence_scores": {{
    "is_pet_friendly": 1.0,
    "allowed_species": 1.0,
    "has_pet_deposit": 1.0,
    "pet_deposit_amount": 1.0,
    "is_deposit_refundable": 1.0,
    "pet_fee_amount": 0.0,
    "pet_fee_currency": 1.0,
    "pet_fee_variations": 1.0,
    "pet_fee_interval": 0.9,
    "max_weight_lbs": 0.0,
    "max_pets_allowed": 0.0,
    "breed_restrictions": 0.0,
    "general_pet_rules": 0.0,
    "has_pet_amenities": 0.0,
    "pet_amenities_list": 0.0,
    "service_animals_allowed": 0.0,
    "emotional_support_animals_allowed": 0.0,
    "service_animal_policy": 0.0,
    "minimum_pet_age": 0.0
  }}
}}

HOTEL INFORMATION:
{context}

Return structured JSON strictly matching the schema with pet_information and confidence_scores as top-level keys.
""".strip()

    def extract(self, web_context: str) -> Dict[str, Any]:
        """Extract pet attributes using OpenRouter/OpenAI"""

        if not self.client:
            logger.warning("Client not configured, skipping attribute extraction")
            return {}

        try:
            system_prompt = self.compose_system_prompt(web_context)

            response = self.client.chat.completions.create(
                model="openai/gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Extract the attributes from the provided context."}
                ],
                response_format={"type": "json_object"},
                temperature=0
            )

            raw_content = response.choices[0].message.content
            parsed_json = json.loads(raw_content)

            print("Raw API Response:")
            print(json.dumps(parsed_json, indent=2))

            # Validate against Pydantic model
            result = HotelPetRelatedInformationWithConfidence(**parsed_json)
            
            print("\nValidated Result:")
            print(json.dumps(result.model_dump(), indent=2))
            
            return result.model_dump()

        except Exception as e:
            logger.error(f"Error extracting pet attributes: {e}")
            import traceback
            traceback.print_exc()
            return {}
