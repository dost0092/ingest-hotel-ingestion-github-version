"""
Database SQL queries
"""
# Raw extraction queries
RAW_EXTRACTION_INSERT = """
INSERT INTO test.hotel_mapped_url (
    url, hotel_name, city, state, country, country_code, address_line_1, "hash", created_at
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
ON CONFLICT (url) 
DO UPDATE SET 
    hotel_name = EXCLUDED.hotel_name,
    city = EXCLUDED.city,
    state = EXCLUDED.state,
    country = EXCLUDED.country,
    country_code = EXCLUDED.country_code,
    address_line_1 = EXCLUDED.address_line_1,
    "hash" = EXCLUDED."hash",
    updated_at = NOW()
RETURNING id;
"""


# Web context update
WEB_CONTEXT_UPDATE = """
UPDATE test.hotel_mapped_url
SET web_context = %s,
    updated_at = NOW()
WHERE id = %s;
"""

# Pet attributes update
PET_ATTRIBUTES_UPDATE = """
UPDATE test.hotel_mapped_url
SET pet_attributes = %s,
    updated_at = NOW()
WHERE id = %s;
"""

# Web slug update
WEB_SLUG_UPDATE = """
UPDATE test.hotel_mapped_url
SET web_slug = %s,
    updated_at = NOW()
WHERE id = %s;
"""

# Check if URL exists
CHECK_URL_EXISTS = """
SELECT id, hash 
FROM test.hotel_mapped_url
WHERE url = %s
  AND web_context IS NOT NULL and pet_attributes IS NOT NULL
LIMIT 1;
"""


