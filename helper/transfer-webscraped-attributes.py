"""
Normalize web-scraped hotel attributes

WHAT THIS DOES:
  1. Remaps hotel_id in test.web_scraped_hotels by matching web_slug → masterfile slug
  2. For each matched hotel, reads raw values from test.web_scraped_hotels
  3. Normalizes values and UPDATES existing rows in ingestion.hotel_attributes
     (rows were bulk-inserted earlier with just the value column)

NORMALIZATION FLOW:
  1. Map attribute name → data type (bool/int/float/str/list[str])
  2. Try normalizer map first (handles 99% of data)
  3. If normalizer returns None but raw value exists → LLM fallback extracts
  4. If LLM can't extract or value is wrong type → is_invalid=True
  5. Currency: LLM can return new currency codes
  6. Everything else (breeds/amenities/species/intervals): only map to existing tags

TYPED COLUMN RULES (matches sabre-parser-llm pattern):
  - bool   → value="True"/"False" (fallback), value_bool=True/False (primary)
  - int    → value="2" (fallback),            value_int=number (primary)
  - float  → value="50.0" (fallback),         value_num=number (primary)
  - list   → value=NULL (per Chris),           value_arr='{...}' (primary)
  - str    → value=text (primary, normalized)

Deploy:
  gcloud functions deploy transfer-webscraped-attributes \
    --runtime python311 \
    --trigger-http \
    --allow-unauthenticated \
    --region us-central1 \
    --project spartan-alcove-430305-v5 \
    --entry-point main

Curl:
  curl https://us-central1-spartan-alcove-430305-v5.cloudfunctions.net/transfer-webscraped-attributes
"""

import functions_framework
import psycopg2
import uuid
from datetime import datetime
import json
import re
from google import genai
from google.genai.types import GenerateContentConfig, Part
import time
import os
from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────────────
# DATABASE CONFIGS
# ─────────────────────────────────────────────────────────────────────

# Load .env file
load_dotenv()

DB_CONFIG_CONSULTANT = {
    'host': os.getenv('DB_HOST'),
    'port': os.getenv('DB_PORT'),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
}
# ─────────────────────────────────────────────────────────────────────
# GEMINI (LLM fallback)
# ─────────────────────────────────────────────────────────────────────

PROJECT_ID = "spartan-alcove-430305-v5"
REGION = "us-central1"
MODEL_ID = "gemini-2.0-flash-001"

def init_gemini():
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=REGION)
    return client

def call_gemini(client, prompt):
    """Call Gemini with retry. Returns response text or None."""
    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=MODEL_ID,
                contents=[Part.from_text(text=prompt)],
                config=GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=256,
                    top_p=0.1,
                ),
            )
            return resp.text.strip()
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                print(f"  Gemini failed after 3 attempts: {e}")
                return None

def llm_extract(client, attr_name, data_type, raw_value, allowed_tags=None):
    """
    LLM fallback: ask Gemini to extract the value from raw text.
    Returns (extracted_value, is_invalid) tuple.
    For currency: LLM can return any valid 3-letter currency code.
    For tags: LLM must pick from allowed_tags only.
    """
    if data_type == 'bool':
        prompt = f"""Extract a boolean value from this text for the attribute "{attr_name}".
Raw value: "{raw_value}"
Reply with ONLY "True" or "False" or "INVALID" if it cannot be determined."""

        result = call_gemini(client, prompt)
        if not result:
            return None, True
        r = result.strip().lower()
        if r == 'true':
            return True, False
        elif r == 'false':
            return False, False
        return None, True

    elif data_type == 'int':
        prompt = f"""Extract an integer value from this text for the attribute "{attr_name}".
Raw value: "{raw_value}"
Reply with ONLY the integer number, or "NULL" if it means no limit/unlimited, or "INVALID" if no number can be extracted."""

        result = call_gemini(client, prompt)
        if not result:
            return None, True
        r = result.strip().upper()
        if r == 'NULL':
            return 'NULL', False  # signals is_null=True
        if r == 'INVALID':
            return None, True
        try:
            return int(re.search(r'-?\d+', r).group()), False
        except (AttributeError, ValueError):
            return None, True

    elif data_type == 'float':
        prompt = f"""Extract a numeric (decimal) value from this text for the attribute "{attr_name}".
Raw value: "{raw_value}"
Reply with ONLY the number (no $ or currency symbols), or "INVALID" if no number can be extracted."""

        result = call_gemini(client, prompt)
        if not result:
            return None, True
        r = result.strip().upper()
        if r == 'INVALID':
            return None, True
        try:
            return float(re.search(r'[\d]+\.?[\d]*', r).group()), False
        except (AttributeError, ValueError):
            return None, True

    elif data_type == 'str' and attr_name == 'pet_fee_currency':
        prompt = f"""Extract the currency code from this text.
Raw value: "{raw_value}"
Reply with ONLY the lowercase 3-letter ISO currency code (e.g., usd, eur, gbp), or "INVALID" if not a currency."""

        result = call_gemini(client, prompt)
        if not result:
            return None, True
        r = result.strip().lower()
        if r == 'invalid' or len(r) != 3:
            return None, True
        return r, False  # currency: LLM can return any valid code

    elif data_type == 'str' and attr_name == 'pet_fee_interval':
        tags_str = ', '.join(ALLOWED_INTERVALS)
        prompt = f"""Extract the fee interval from this text for pet fees.
Raw value: "{raw_value}"
Allowed values: {tags_str}
Reply with ONLY one of the allowed values, or "INVALID" if none match."""

        result = call_gemini(client, prompt)
        if not result:
            return None, True
        r = result.strip().lower()
        if r in ALLOWED_INTERVALS:
            return r, False
        return None, True  # don't add new intervals

    elif data_type == 'list[str]' and allowed_tags:
        tags_str = ', '.join(allowed_tags)
        prompt = f"""Extract standardized tags from this text for the attribute "{attr_name}".
Raw value: "{raw_value}"
Allowed tags: {tags_str}
Reply with ONLY the matching tags as a comma-separated list, or "INVALID" if none match."""

        result = call_gemini(client, prompt)
        if not result:
            return None, True
        r = result.strip().upper()
        if r == 'INVALID':
            return None, True
        extracted = [t.strip() for t in r.split(',')]
        valid = [t for t in extracted if t in allowed_tags]
        if valid:
            return valid, False
        return None, True  # don't add new tags

    return None, True


# ─────────────────────────────────────────────────────────────────────
# ATTRIBUTE TYPE UUIDs (from public.attribute_types)
# ─────────────────────────────────────────────────────────────────────
ATTR_MAP = {
    'is_pet_friendly': '09a1c66f-a780-4ba2-99e3-feaeea25d41d',
    'pet_fee_amount': 'c86a1fb4-455d-48b3-aeca-4a73cbe6438e',
    'pet_fee_interval': 'b7486a97-3eb6-4d58-af7f-6e881a9feb05',
    'max_pets_allowed': '26f8aae7-1a20-4683-b8ea-d877db9f0cd9',
    'max_weight_lbs': '03a7571a-db77-4c99-9a24-87a8cba0f5a9',
    'allowed_species': '6030e1c8-75a7-490c-b64d-5b423fcf53cb',
    'breed_restrictions': '93539e95-dc41-405b-9664-e81017281fb8',
    'has_pet_deposit': 'f5c45b2d-3083-41bd-b596-b6797e02f3be',
    'is_deposit_refundable': '267ea64d-d433-4836-87f1-397dfaaec55c',
    'pet_fee_currency': '07d1da9d-d55c-4bf0-9570-3f24f9b8ad17',
    'pet_fee_variations': 'fc86ad4d-b96c-4998-96ca-236d99152c97',
    'pet_amenities_list': '5d3d2e74-feb2-4438-b50a-9a503289c236',
    'has_pet_amenities': '1e8212be-6385-4b60-ba90-27f3c540ce9a',
    'general_pet_rules': 'd7e360fb-350c-4508-aa7b-dfd015bbe089',
    'pet_deposit_amount': 'a990d55c-0ae3-4ebd-a629-7ac1ee3aea7f',
    # These 4 will be looked up at runtime from public.attribute_types.
    # If they don't exist yet, insert_attr() safely skips them (ATTR_MAP returns None).
    # 'service_animals_allowed': None,  # resolved at runtime
    # 'emotional_support_animals_allowed': None,  # resolved at runtime
    # 'minimum_pet_age': None,  # resolved at runtime
    # 'service_animal_policy': None,  # resolved at runtime
}

# ─────────────────────────────────────────────────────────────────────
# DATA TYPE MAP — which typed column to fill for each attribute
# ─────────────────────────────────────────────────────────────────────
ATTR_DATA_TYPES = {
    'is_pet_friendly': 'bool',
    'has_pet_deposit': 'bool',
    'is_deposit_refundable': 'bool',
    'has_pet_amenities': 'bool',
    'max_pets_allowed': 'int',
    'max_weight_lbs': 'int',
    'pet_fee_amount': 'float',
    'pet_deposit_amount': 'float',
    'pet_fee_currency': 'str',
    'pet_fee_interval': 'str',
    'allowed_species': 'list[str]',
    'breed_restrictions': 'list[str]',
    'pet_amenities_list': 'list[str]',
    'pet_fee_variations': 'list[str]',
    'general_pet_rules': 'list[str]',
    'service_animals_allowed': 'bool',
    'emotional_support_animals_allowed': 'bool',
    'minimum_pet_age': 'int',
    'service_animal_policy': 'str',
}

# ─────────────────────────────────────────────────────────────────────
# ALLOWED TAGS (from Notion dropdown docs)
# ─────────────────────────────────────────────────────────────────────
ALLOWED_SPECIES_TAGS = [
    'PET_TYPE_DOG', 'PET_TYPE_CAT', 'PET_TYPE_BIRD', 'PET_TYPE_FISH',
    'PET_TYPE_SMALL', 'PET_TYPE_ALL', 'PET_TYPE_SERVICE', 'PET_TYPE_DOMESTIC'
]

BREED_TAGS = [
    'BREED_PIT_BULL', 'BREED_ROTTWEILER', 'BREED_GERMAN_SHEPHERD',
    'BREED_DOBERMAN', 'BREED_HUSKY', 'BREED_AKITA', 'BREED_MASTIFF',
    'BREED_CHOW_CHOW', 'BREED_GREAT_DANE', 'BREED_WOLF', 'BREED_BOXER',
    'BREED_AMERICAN_BULLDOG', 'BREED_STAFFORDSHIRE_TERRIER',
    'BREED_ALASKAN_MALAMUTE', 'BREED_CANE_CORSO', 'BREED_AGGRESSIVE',
    'BREED_LARGE', 'BREED_CONTACT',
    'BREED_DOGO_ARGENTINO', 'BREED_PRESA_CANARIO', 'BREED_BELGIAN_MALINOIS',
    'BREED_ST_BERNARD', 'BREED_BULL_TERRIER'
]

AMENITY_TAGS = [
    'AMENITY_PET_BEDS', 'AMENITY_PET_BOWLS', 'AMENITY_PET_TREATS',
    'AMENITY_RELIEF_AREA', 'AMENITY_PET_MENU', 'AMENITY_PET_TOYS',
    'AMENITY_KENNEL', 'AMENITY_PET_SITTING', 'AMENITY_DOG_WALKING',
    'AMENITY_WASTE_BAGS', 'AMENITY_WELCOME_KIT', 'AMENITY_FENCED_AREA',
    'AMENITY_DOG_WASH', 'AMENITY_TRAILS'
]

ALLOWED_INTERVALS = ['per-night', 'per-stay', 'per-day', 'per-week', 'one-time']
ALLOWED_CURRENCIES = ['usd', 'eur', 'gbp', 'aud', 'cad', 'chf', 'jpy', 'cny', 'inr', 'mxn', 'hkd']


# ─────────────────────────────────────────────────────────────────────
# TYPE NORMALIZERS — convert raw values to the right Python type
# ─────────────────────────────────────────────────────────────────────

def normalize_bool(raw):
    """True/False/"yes"/"no"/"1"/"0" → Python bool"""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    s = str(raw).lower().strip()
    if s in ('true', 'yes', '1', 't', 'y'):
        return True
    if s in ('false', 'no', '0', 'f', 'n'):
        return False
    return None


def normalize_int(raw):
    """'2 pets' → 2, '75 lbs' → 75"""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    match = re.search(r'\d+', str(raw).strip())
    return int(match.group()) if match else None


def normalize_float(raw):
    """'$50.00' → 50.0, '$25 per night' → 25.0"""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    match = re.search(r'[\d]+\.?[\d]*', str(raw).strip())
    return float(match.group()) if match else None


# ─────────────────────────────────────────────────────────────────────
# TAG NORMALIZERS — convert raw text to standardized tags
# ─────────────────────────────────────────────────────────────────────

def normalize_species(raw):
    """'dog, cat' → ['PET_TYPE_DOG', 'PET_TYPE_CAT']"""
    if not raw:
        return None
    s = str(raw).lower()
    tags = []
    if 'dog' in s or 'canine' in s:
        tags.append('PET_TYPE_DOG')
    if 'cat' in s:
        tags.append('PET_TYPE_CAT')
    if 'bird' in s:
        tags.append('PET_TYPE_BIRD')
    if 'fish' in s:
        tags.append('PET_TYPE_FISH')
    if 'rabbit' in s or 'hamster' in s or 'guinea' in s or 'small pet' in s or 'small animal' in s:
        tags.append('PET_TYPE_SMALL')
    if ('all' in s and ('pet' in s or 'animal' in s)) or 'all types' in s:
        tags.append('PET_TYPE_ALL')
    if 'service' in s or 'guide dog' in s or 'assistance' in s:
        tags.append('PET_TYPE_SERVICE')
    if 'domestic' in s:
        tags.append('PET_TYPE_DOMESTIC')
    return tags if tags else None


def normalize_breeds(raw):
    """'Pit Bull, Rottweiler' → ['BREED_PIT_BULL', 'BREED_ROTTWEILER']"""
    if not raw:
        return None
    s = str(raw).lower()
    # Skip "no restriction" / "n/a" / "none" values
    if s.strip() in ('n/a', 'none', 'no', 'no breed restriction', 'no breed restrictions',
                      'no aggressive breeds'):
        return None
    tags = []
    if 'pit' in s or 'pitbull' in s:
        tags.append('BREED_PIT_BULL')
    if 'rottweiler' in s:
        tags.append('BREED_ROTTWEILER')
    if 'german shepherd' in s or 'german-shepherd' in s:
        tags.append('BREED_GERMAN_SHEPHERD')
    if 'doberman' in s:
        tags.append('BREED_DOBERMAN')
    if 'husky' in s or 'siberian' in s:
        tags.append('BREED_HUSKY')
    if 'akita' in s:
        tags.append('BREED_AKITA')
    if 'mastiff' in s:
        tags.append('BREED_MASTIFF')
    if 'wolf' in s:
        tags.append('BREED_WOLF')
    if 'chow' in s:
        tags.append('BREED_CHOW_CHOW')
    if 'great dane' in s:
        tags.append('BREED_GREAT_DANE')
    if 'boxer' in s:
        tags.append('BREED_BOXER')
    if 'bulldog' in s and 'american' in s:
        tags.append('BREED_AMERICAN_BULLDOG')
    if 'staffordshire' in s:
        tags.append('BREED_STAFFORDSHIRE_TERRIER')
    if 'malamute' in s:
        tags.append('BREED_ALASKAN_MALAMUTE')
    if 'cane corso' in s:
        tags.append('BREED_CANE_CORSO')
    if 'aggressive' in s:
        tags.append('BREED_AGGRESSIVE')
    if 'large breed' in s:
        tags.append('BREED_LARGE')
    if 'contact' in s:
        tags.append('BREED_CONTACT')
    if 'dogo' in s or 'argentino' in s:
        tags.append('BREED_DOGO_ARGENTINO')
    if 'presa' in s or 'canario' in s:
        tags.append('BREED_PRESA_CANARIO')
    if 'belgian' in s or 'malinois' in s:
        tags.append('BREED_BELGIAN_MALINOIS')
    if 'st. bernard' in s or 'saint bernard' in s or 'st bernard' in s:
        tags.append('BREED_ST_BERNARD')
    if 'bull terrier' in s and 'staffordshire' not in s:
        tags.append('BREED_BULL_TERRIER')
    return tags if tags else None


def normalize_amenities(raw):
    """'pet beds, bowls, relief area' → ['AMENITY_PET_BEDS', ...]"""
    if not raw:
        return None
    s = str(raw).lower()
    tags = []
    if 'bed' in s:
        tags.append('AMENITY_PET_BEDS')
    if 'bowl' in s or 'dish' in s:
        tags.append('AMENITY_PET_BOWLS')
    if 'treat' in s or 'biscuit' in s:
        tags.append('AMENITY_PET_TREATS')
    if 'relief' in s or 'dog run' in s or 'potty' in s or 'dog park' in s or 'waste station' in s:
        tags.append('AMENITY_RELIEF_AREA')
    if 'menu' in s or 'dining' in s or 'pet food' in s or 'dog food' in s:
        tags.append('AMENITY_PET_MENU')
    if 'toy' in s:
        tags.append('AMENITY_PET_TOYS')
    if 'kennel' in s or 'crate' in s:
        tags.append('AMENITY_KENNEL')
    if 'sitting' in s or 'daycare' in s:
        tags.append('AMENITY_PET_SITTING')
    if 'walking' in s or 'dog_walking' in s:
        tags.append('AMENITY_DOG_WALKING')
    if 'waste' in s or 'poop' in s or 'bag' in s:
        tags.append('AMENITY_WASTE_BAGS')
    if 'welcome' in s and 'kit' in s:
        tags.append('AMENITY_WELCOME_KIT')
    if 'fenc' in s or 'backyard' in s or 'private' in s and 'yard' in s:
        tags.append('AMENITY_FENCED_AREA')
    if 'wash' in s or 'groom' in s or 'bath' in s:
        tags.append('AMENITY_DOG_WASH')
    if 'trail' in s or 'hik' in s:
        tags.append('AMENITY_TRAILS')
    return tags if tags else None


def normalize_interval(raw):
    """'Per Stay' → 'per-stay' (hyphens, not underscores)"""
    if not raw:
        return None
    s = str(raw).lower().strip()
    if 'stay' in s:
        return 'per-stay'
    if 'night' in s:
        return 'per-night'
    if 'day' in s:
        return 'per-day'
    if 'week' in s:
        return 'per-week'
    if 'one' in s and 'time' in s:
        return 'one-time'
    return None


def normalize_currency(raw):
    """'$' → 'usd', 'EUR' → 'eur'"""
    if not raw:
        return None
    s = str(raw).lower().strip()
    mapping = {
        '$': 'usd', 'usd': 'usd', 'dollar': 'usd', 'us': 'usd',
        'eur': 'eur', 'euro': 'eur', 'gbp': 'gbp', 'pound': 'gbp',
        'aud': 'aud', 'cad': 'cad', 'chf': 'chf', 'jpy': 'jpy',
        'cny': 'cny', 'inr': 'inr', 'mxn': 'mxn', 'hkd': 'hkd',
    }
    for key, code in mapping.items():
        if key in s:
            return code
    return None


def list_to_pg_arr(tags):
    """['PET_TYPE_DOG', 'PET_TYPE_CAT'] → '{PET_TYPE_DOG,PET_TYPE_CAT}'"""
    return '{' + ','.join(tags) + '}'


def extract_json_field(raw, field):
    """Extract a field from JSON string like {"raw": "..."} or {"policy": "..."}"""
    if not raw:
        return None
    s = str(raw).strip()
    if s.startswith('{'):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, dict) and field in parsed:
                return parsed[field]
        except (json.JSONDecodeError, TypeError):
            pass
    return s  # not JSON, return as-is


def text_to_pg_arr(raw):
    """Split free-form text into postgres array, quoting items with commas"""
    if not raw:
        return None
    text = extract_json_field(raw, 'raw')  # handle {"raw": "..."} format
    if not text:
        return None
    items = [item.strip() for item in re.split(r'[|\n;]', str(text)) if item.strip()]
    if not items:
        return None
    escaped = []
    for item in items:
        if ',' in item or '"' in item:
            item = '"' + item.replace('"', '\\"') + '"'
        escaped.append(item)
    return '{' + ','.join(escaped) + '}'


def policy_to_pg_arr(raw):
    """Split policy text into sentences → postgres array.
    Splits on newline, semicolon, bullet — NOT on '.' which breaks '$75.00'."""
    if not raw:
        return None
    text = extract_json_field(raw, 'policy')  # handle {"policy": "..."} format
    if not text:
        return None
    # Split on '. ' (period+space), newline, semicolon, bullet — not bare '.'
    items = [item.strip() for item in re.split(r'\.\s|\n|;|•', str(text))
             if item.strip() and len(item.strip()) > 5]
    if not items:
        return None
    escaped = []
    for item in items:
        if ',' in item or '"' in item:
            item = '"' + item.replace('"', '\\"') + '"'
        escaped.append(item)
    return '{' + ','.join(escaped) + '}'


# ─────────────────────────────────────────────────────────────────────
# UPDATE — normalizes and fills typed columns on existing rows
# ─────────────────────────────────────────────────────────────────────

def upsert_attr(cur, hotel_id, attr_name, value=None, value_bool=None,
                value_int=None, value_num=None, value_arr=None,
                is_null=False, is_invalid=False):
    """
    Updates existing web-scraper row, or INSERTs a new one if no row exists.
    Returns 'updated', 'inserted', or 'skipped'.
    """
    attr_type_id = ATTR_MAP.get(attr_name)
    if not attr_type_id:
        return 'skipped'

    data_type = ATTR_DATA_TYPES.get(attr_name, 'str')
    now = datetime.now()

    # value column: text fallback for bool/int/float (matches sabre-parser-llm pattern)
    # list[str]: value=NULL per Chris
    # str: value is the primary column
    if data_type == 'bool' and value_bool is not None:
        db_value = str(value_bool)        # "True" or "False"
    elif data_type == 'int' and value_int is not None:
        db_value = str(value_int)         # "2", "75"
    elif data_type == 'float' and value_num is not None:
        db_value = str(value_num)         # "50.0"
    elif data_type == 'list[str]':
        db_value = None                   # NULL per Chris
    else:
        db_value = str(value) if value is not None else None

    # Try UPDATE first
    cur.execute("""
        UPDATE ingestion.hotel_attributes
        SET value = %s,
            value_bool = %s,
            value_int = %s,
            value_num = %s,
            value_arr = %s,
            confidence = %s,
            enabled = %s,
            updated_at = %s,
            is_null = %s,
            is_invalid = %s
        WHERE hotel_id = %s
        AND attribute_type_id = %s
        AND generated_by = 'web-scraper'
        AND enabled = true
    """, (
        db_value,
        value_bool,
        value_int,
        value_num,
        value_arr,
        0.85 if not is_invalid else 0.0,
        False if is_invalid else True,
        now,
        is_null,
        is_invalid,
        str(hotel_id),
        attr_type_id,
    ))

    if cur.rowcount > 0:
        return 'updated'

    # No existing row — INSERT new one
    cur.execute("""
        INSERT INTO ingestion.hotel_attributes (
            id, hotel_id, attribute_type_id,
            value, value_bool, value_int, value_num, value_arr,
            confidence, generated_by, created_by, enabled, effective_date,
            created_at, updated_at, is_null, is_invalid
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        str(uuid.uuid4()),
        str(hotel_id),
        attr_type_id,
        db_value,
        value_bool,
        value_int,
        value_num,
        value_arr,
        0.85 if not is_invalid else 0.0,
        'web-scraper',
        'system',
        False if is_invalid else True,
        now,
        now,
        now,
        is_null,
        is_invalid,
    ))
    return 'inserted'


# ─────────────────────────────────────────────────────────────────────
# SLUG REMAP
# ─────────────────────────────────────────────────────────────────────

def resolve_missing_attr_types(cur):
    """Look up the 4 attribute types that may not exist yet.
    If they exist in public.attribute_types, add their UUID to ATTR_MAP."""
    missing = ['service_animals_allowed', 'emotional_support_animals_allowed',
               'minimum_pet_age', 'service_animal_policy']
    for name in missing:
        cur.execute("SELECT id FROM public.attribute_types WHERE name = %s", (name,))
        row = cur.fetchone()
        if row:
            ATTR_MAP[name] = str(row[0])
            print(f"  Resolved: {name} → {row[0]}")
        else:
            print(f"  Not found: {name} (will skip)")


# ─────────────────────────────────────────────────────────────────────
# PROCESS ONE ATTRIBUTE — normalizer first, LLM fallback, is_invalid
# ─────────────────────────────────────────────────────────────────────

def process_attr(cur, client, hotel_id, attr_name, raw_value, normalizer_result,
                 data_type, stats, allowed_tags=None):
    """
    Unified processing for one attribute:
    1. If normalizer succeeded → update with typed column
    2. If normalizer failed but raw exists → LLM fallback
    3. If LLM fails → update with is_invalid=True
    """
    # Normalizer succeeded
    if normalizer_result is not None:
        result = 'skipped'
        if data_type == 'bool':
            result = upsert_attr(cur, hotel_id, attr_name, value_bool=normalizer_result)
        elif data_type == 'int':
            result = upsert_attr(cur, hotel_id, attr_name, value_int=normalizer_result)
        elif data_type == 'float':
            result = upsert_attr(cur, hotel_id, attr_name, value_num=normalizer_result)
        elif data_type == 'str':
            result = upsert_attr(cur, hotel_id, attr_name, value=normalizer_result)
        elif data_type == 'list[str]':
            result = upsert_attr(cur, hotel_id, attr_name, value_arr=normalizer_result)
        if result == 'updated':
            stats['updated'] += 1
            print(f"    ✓ {attr_name} = {normalizer_result}")
        elif result == 'inserted':
            stats['inserted'] += 1
            print(f"    + {attr_name} = {normalizer_result} (new row)")
        return

    # Normalizer failed — but do we have raw data?
    if raw_value is None or (isinstance(raw_value, str) and raw_value.strip() == ''):
        return  # no data, skip entirely

    # LLM fallback
    print(f"    ⚡ {attr_name} → LLM fallback (raw: {str(raw_value)[:80]})")
    llm_val, invalid = llm_extract(client, attr_name, data_type, raw_value, allowed_tags)
    stats['llm_calls'] += 1

    if invalid or llm_val is None:
        # LLM couldn't extract → mark as invalid
        result = upsert_attr(cur, hotel_id, attr_name, is_invalid=True)
        if result in ('updated', 'inserted'):
            stats['invalid'] += 1
            print(f"    ✗ {attr_name} INVALID (LLM could not extract)")
        return

    # LLM returned 'NULL' for int → means "no limit"
    if data_type == 'int' and llm_val == 'NULL':
        result = upsert_attr(cur, hotel_id, attr_name, is_null=True)
        if result == 'updated':
            stats['updated'] += 1
            print(f"    ✓ {attr_name} = NULL (no limit)")
        elif result == 'inserted':
            stats['inserted'] += 1
            print(f"    + {attr_name} = NULL (no limit, new row)")
        return

    # LLM succeeded
    result = 'skipped'
    if data_type == 'bool':
        result = upsert_attr(cur, hotel_id, attr_name, value_bool=llm_val)
    elif data_type == 'int':
        result = upsert_attr(cur, hotel_id, attr_name, value_int=llm_val)
    elif data_type == 'float':
        result = upsert_attr(cur, hotel_id, attr_name, value_num=llm_val)
    elif data_type == 'str':
        result = upsert_attr(cur, hotel_id, attr_name, value=llm_val)
    elif data_type == 'list[str]':
        arr = list_to_pg_arr(llm_val)
        result = upsert_attr(cur, hotel_id, attr_name, value_arr=arr)
    if result == 'updated':
        stats['updated'] += 1
        print(f"    ✓ {attr_name} = {llm_val} (via LLM)")
    elif result == 'inserted':
        stats['inserted'] += 1
        print(f"    + {attr_name} = {llm_val} (via LLM, new row)")


# ─────────────────────────────────────────────────────────────────────
# TRANSFER — the main loop
# ─────────────────────────────────────────────────────────────────────

def transfer_attributes(cur, conn):
    """
    For each matched hotel: normalize raw values → UPDATE existing rows with typed columns.
    Rows already exist from bulk SQL INSERT. This fills value_bool/int/num/arr + normalizes value.
    Normalizer first, LLM fallback if normalizer fails, is_invalid if both fail.
    Commits after each hotel so progress is never lost.
    """
    client = init_gemini()

    # Resolve the 4 attribute types that may not exist yet
    print("Resolving attribute types...")
    resolve_missing_attr_types(cur)

    cur.execute("""
        SELECT hotel_id,                            -- 0
               is_pet_friendly,                     -- 1  bool
               pet_fee_night,                       -- 2  float
               pet_fee_total_max,                   -- 3  float (fallback for fee)
               pet_fee_interval,                    -- 4  str
               max_pets,                            -- 5  int (values >10 are weight, not pet count)
               allowed_pet_types,                   -- 6  list[str]
               breed_restrictions,                  -- 7  list[str]
               has_pet_deposit,                     -- 8  bool
               is_deposit_refundable,               -- 9  bool
               pet_fee_currency,                    -- 10 str
               pet_fee_variations,                  -- 11 list[str] (JSON: {"raw": "..."})
               pet_amenities,                       -- 12 list[str] (general hotel amenities)
               has_pet_amenities,                   -- 13 bool
               pet_policy,                          -- 14 list[str] (JSON: {"policy": "..."} or raw text)
               pet_fee_deposit                      -- 15 float → pet_deposit_amount
        FROM test.web_scraped_hotels
        WHERE hotel_id IS NOT NULL
    """)

    rows = cur.fetchall()
    total = len(rows)
    stats = {'hotels': total, 'updated': 0, 'inserted': 0, 'invalid': 0, 'llm_calls': 0}

    print(f"Processing {total} matched hotels...")

    for i, row in enumerate(rows):
        hotel_id = row[0]

        print(f"\n[{i+1}/{total}] Hotel {hotel_id}")

        # ── BOOLEANS (4) ──

        process_attr(cur, client, hotel_id, 'is_pet_friendly',
                     row[1], normalize_bool(row[1]), 'bool', stats)

        process_attr(cur, client, hotel_id, 'has_pet_deposit',
                     row[8], normalize_bool(row[8]), 'bool', stats)

        process_attr(cur, client, hotel_id, 'is_deposit_refundable',
                     row[9], normalize_bool(row[9]), 'bool', stats)

        process_attr(cur, client, hotel_id, 'has_pet_amenities',
                     row[13], normalize_bool(row[13]), 'bool', stats)

        # ── INTEGERS (2) ──
        # max_pets column has weight data mixed in.
        # 1-10 = actual pet count. >10 = weight in lbs.
        raw_max_pets = row[5]
        parsed_max_pets = normalize_int(raw_max_pets)
        if parsed_max_pets is not None:
            if parsed_max_pets <= 10:
                process_attr(cur, client, hotel_id, 'max_pets_allowed',
                             raw_max_pets, parsed_max_pets, 'int', stats)
            else:
                process_attr(cur, client, hotel_id, 'max_weight_lbs',
                             raw_max_pets, parsed_max_pets, 'int', stats)
        elif raw_max_pets is not None:
            # Normalizer failed on non-null → LLM fallback
            process_attr(cur, client, hotel_id, 'max_pets_allowed',
                         raw_max_pets, None, 'int', stats)

        # ── FLOATS (2) ──

        raw_fee = row[2] or row[3]  # pet_fee_night, fallback pet_fee_total_max
        fee_val = normalize_float(raw_fee)
        # Cap: pet fees > 1000 are garbage data (years, currency conversions, etc.)
        if fee_val is not None and fee_val > 1000:
            result = upsert_attr(cur, hotel_id, 'pet_fee_amount', is_invalid=True)
            if result in ('updated', 'inserted'):
                stats['invalid'] += 1
                print(f"    ✗ pet_fee_amount INVALID (${fee_val} > $1000 cap)")
        else:
            process_attr(cur, client, hotel_id, 'pet_fee_amount',
                         raw_fee, fee_val, 'float', stats)

        raw_deposit = row[15]  # pet_fee_deposit → pet_deposit_amount
        val_deposit = normalize_float(raw_deposit)
        if val_deposit is not None and val_deposit > 0:
            process_attr(cur, client, hotel_id, 'pet_deposit_amount',
                         raw_deposit, val_deposit, 'float', stats)
        elif raw_deposit is not None and val_deposit is None:
            process_attr(cur, client, hotel_id, 'pet_deposit_amount',
                         raw_deposit, None, 'float', stats)

        # ── STRINGS (2) ──

        raw_currency = row[10]
        mapped_currency = normalize_currency(raw_currency)
        if mapped_currency and mapped_currency in ALLOWED_CURRENCIES:
            process_attr(cur, client, hotel_id, 'pet_fee_currency',
                         raw_currency, mapped_currency, 'str', stats)
        elif raw_currency:
            # Normalizer failed → LLM can return any valid currency code
            process_attr(cur, client, hotel_id, 'pet_fee_currency',
                         raw_currency, None, 'str', stats)

        raw_interval = row[4]
        mapped_interval = normalize_interval(raw_interval)
        if mapped_interval and mapped_interval in ALLOWED_INTERVALS:
            process_attr(cur, client, hotel_id, 'pet_fee_interval',
                         raw_interval, mapped_interval, 'str', stats)
        elif raw_interval:
            # Normalizer failed → LLM picks from allowed intervals only
            process_attr(cur, client, hotel_id, 'pet_fee_interval',
                         raw_interval, None, 'str', stats)

        # ── LISTS (5) ──

        raw_species = row[6]
        tags = normalize_species(raw_species)
        if tags:
            valid = [t for t in tags if t in ALLOWED_SPECIES_TAGS]
            process_attr(cur, client, hotel_id, 'allowed_species',
                         raw_species, list_to_pg_arr(valid) if valid else None,
                         'list[str]', stats, ALLOWED_SPECIES_TAGS)
        elif raw_species:
            process_attr(cur, client, hotel_id, 'allowed_species',
                         raw_species, None, 'list[str]', stats, ALLOWED_SPECIES_TAGS)

        raw_breeds = row[7]
        tags = normalize_breeds(raw_breeds)
        if tags:
            valid = [t for t in tags if t in BREED_TAGS]
            process_attr(cur, client, hotel_id, 'breed_restrictions',
                         raw_breeds, list_to_pg_arr(valid) if valid else None,
                         'list[str]', stats, BREED_TAGS)
        elif raw_breeds:
            process_attr(cur, client, hotel_id, 'breed_restrictions',
                         raw_breeds, None, 'list[str]', stats, BREED_TAGS)

        # pet_amenities contains general hotel amenities (WiFi, parking, etc.)
        # NOT pet-specific. Only insert if normalizer finds actual pet amenity tags.
        # Do NOT fall back to LLM — general amenities would just confuse it.
        raw_amenities = row[12]
        tags = normalize_amenities(raw_amenities)
        if tags:
            valid = [t for t in tags if t in AMENITY_TAGS]
            if valid:
                result = upsert_attr(cur, hotel_id, 'pet_amenities_list', value_arr=list_to_pg_arr(valid))
                if result == 'updated':
                    stats['updated'] += 1
                    print(f"    ✓ pet_amenities_list = {valid}")
                elif result == 'inserted':
                    stats['inserted'] += 1
                    print(f"    + pet_amenities_list = {valid} (new row)")

        raw_variations = row[11]
        arr = text_to_pg_arr(raw_variations)
        process_attr(cur, client, hotel_id, 'pet_fee_variations',
                     raw_variations, arr, 'list[str]', stats)

        raw_policy = row[14]
        arr = policy_to_pg_arr(raw_policy)
        process_attr(cur, client, hotel_id, 'general_pet_rules',
                     raw_policy, arr, 'list[str]', stats)

        # Commit after each hotel — progress is never lost
        conn.commit()

    print(f"\n{'=' * 60}")
    print(f"DONE — {total} hotels processed")
    print(f"  Updated:   {stats['updated']}")
    print(f"  Inserted:  {stats['inserted']}")
    print(f"  Invalid:   {stats['invalid']}")
    print(f"  LLM calls: {stats['llm_calls']}")
    print(f"{'=' * 60}")

    return stats


# ─────────────────────────────────────────────────────────────────────
# ENTRY POINTS
# ─────────────────────────────────────────────────────────────────────

def remap_slugs(cur):
    """Re-match web_slug → masterfile slug to set hotel_id"""
    cur.execute("UPDATE test.web_scraped_hotels SET hotel_id = NULL")
    cur.execute("""
        UPDATE test.web_scraped_hotels ws
        SET hotel_id = hm.id
        FROM ingestion.hotel_masterfile hm
        WHERE ws.web_slug = hm.slug
        AND ws.web_slug IS NOT NULL
    """)
    return cur.rowcount


@functions_framework.http
def main(request):
    """HTTP entry point for Cloud Functions"""
    print("=" * 60)
    print("NORMALIZE WEB-SCRAPED ATTRIBUTES — START")
    print("=" * 60)

    # Step 1: Remap hotel_id via slug match
    print("\n[STEP 1] Remapping hotel_id via slug...")
    conn_consultant = psycopg2.connect(**DB_CONFIG_CONSULTANT)
    cur_consultant = conn_consultant.cursor()
    try:
        matched = remap_slugs(cur_consultant)
        conn_consultant.commit()
        print(f"  Matched: {matched} hotels")
    finally:
        cur_consultant.close()
        conn_consultant.close()

    # Step 2: Normalize existing rows
    print("\n[STEP 2] Normalizing attributes...")
    conn = psycopg2.connect(**DB_CONFIG_POSTGRES)
    cur = conn.cursor()
    try:
        stats = transfer_attributes(cur, conn)
        stats['slug_matched'] = matched
        print("\n[DONE] All hotels committed ✓")
        return json.dumps(stats), 200
    except Exception as e:
        conn.rollback()
        print(f"\n[ERROR] Rolled back: {e}")
        return json.dumps({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("TRANSFER WEB-SCRAPED ATTRIBUTES")
    print("=" * 60)

    # Step 1: Remap slugs
    print("\n[1] Remapping slugs...")
    conn_consultant = psycopg2.connect(**DB_CONFIG_CONSULTANT)
    cur_consultant = conn_consultant.cursor()
    matched = remap_slugs(cur_consultant)
    conn_consultant.commit()
    print(f"  Matched: {matched}")
    cur_consultant.close()
    conn_consultant.close()

    # Step 2: Transfer
    print("\n[2] Transferring attributes...")
    conn_postgres = psycopg2.connect(**DB_CONFIG_POSTGRES)
    cur_postgres = conn_postgres.cursor()
    stats = transfer_attributes(cur_postgres, conn_postgres)
    stats['slug_matched'] = matched

    print(f"\n{'=' * 60}")
    print(f"  Slug matched: {stats['slug_matched']}")
    print(f"  Hotels:       {stats['hotels']}")
    print(f"  Updated:      {stats['updated']}")
    print(f"  Inserted:     {stats['inserted']}")
    print(f"  Invalid:      {stats['invalid']}")
    print(f"  LLM calls:    {stats['llm_calls']}")
    print(f"{'=' * 60}")

    cur_postgres.close()
    conn_postgres.close()
