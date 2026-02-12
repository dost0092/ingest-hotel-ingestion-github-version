"""
Address parsing utilities
"""
from typing import Dict, Any
import psycopg2
import os
from db.db_connection import get_db_cursor  # Assuming you have a database connection module

def get_state_code(state_name: str) -> str:
    """Get state code from state name using PostgreSQL database lookup"""
    if not state_name:
        return ""
    
    try:
        # Use your existing database connection
        with get_db_cursor() as cur:
            # Query for state code from the test.us_states table
            cur.execute(
                "SELECT state_code FROM test.us_states WHERE state_name = %s",
                (state_name,)
            )
            
            result = cur.fetchone()
            return result[0] if result else ""
    except Exception as e:
        print(f"Error fetching state code: {e}")
        return ""

def parse_address(address_str: str) -> Dict[str, str]:
    """
    Parse address string into components
    Example: "225 E. Apache Blvd, Tempe, Arizona, 85281, USA"
    """
    if not address_str:
        return {
            "address_line_1": "", 
            "city": "", 
            "state": "", 
            "zip": "", 
            "country": "", 
            "country_code": "",
            "state_code": ""  # Added state_code field
        }
    
    # Remove extra spaces and split by comma
    parts = [part.strip() for part in address_str.split(',')]
    
    # Default values
    address_line_1 = parts[0] if len(parts) > 0 else ""
    city = parts[1] if len(parts) > 1 else ""
    state_name = parts[2] if len(parts) > 2 else ""
    zip_code = parts[3] if len(parts) > 3 else ""
    country = parts[4] if len(parts) > 4 else ""
    
    # Extract country code (first two letters)
    country_code = country[:2].upper() if country else "US"
    
    # Get state code from PostgreSQL database
    state_code = get_state_code(state_name)
    
    return {
        "address_line_1": address_line_1,
        "city": city,
        "state": state_name,  # Keeping original state name
        "state_code": state_code,  # Adding state code
        "zip": zip_code,
        "country": country,
        "country_code": country_code
    }