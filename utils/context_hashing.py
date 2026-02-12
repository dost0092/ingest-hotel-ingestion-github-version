"""
Context hashing utilities
"""
import hashlib

def _normalize_context(context: str) -> str:
    """Normalize context by removing extra spaces and newlines"""
    return context.strip().lower().replace(" ", "").replace("\n", " ")

def _hash_context(context: str) -> str:
    """Generate MD5 hash of normalized context"""
    normalized_context = _normalize_context(context)
    return hashlib.md5(normalized_context.encode("utf-8")).hexdigest()

def generate_raw_content_hash(hotel_data: dict) -> str:
    """Generate hash from hotel data"""
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
    return _hash_context(raw_content)