"""
Generate and Update web_slug for test.web_scraped_hotels table
Based on: COUNTRY + STATE + CITY + NAME + ADDRESS_LINE_1
Handles: special characters, accents, spaces, commas, apostrophes, periods, etc.

This script:
1. Connects to the database
2. Creates backup table (optional)
3. Adds web_slug column if not exists
4. Generates slugs from ALL fields (country, state, city, name, address)
5. Updates the database
6. Shows verification results

Example:
"US", "TX", "San Antonio", "Hyatt Hotel", "1021 Hospitality Ln"
→ "us-tx-sanantonio-hyatthotel-1021hospitalityln"
"""

import psycopg2
import re
import unicodedata
from typing import Optional
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Database connection parameters (from .env)
DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'port': os.getenv('DB_PORT'),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
}

# =====================================================
# SLUG GENERATION FUNCTIONS
# =====================================================

def remove_accents(text: str) -> str:
    """
    Remove accents from characters (é → e, ñ → n, etc.)
    """
    if not text:
        return ""
    # Normalize to NFD (decomposed form) and filter out combining characters
    nfd = unicodedata.normalize('NFD', text)
    return ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')


def normalize_address_slug(address: str) -> str:
    """
    Normalize address for slug generation:
    1. Remove accents (é → e)
    2. Lowercase everything
    3. Remove periods, commas, apostrophes, and other special characters
    4. Remove spaces to create continuous string
    5. Keep only alphanumeric characters
    
    Examples:
    "1000 Main Street" → "1000mainstreet"
    "1000 N. Permeter Rd." → "1000nperrneterrd"
    "102-40 Ditmars Boulevard" → "10240ditmarsboulevard"
    "1,000 Market St" → "1000marketst"
    "O'Reilly's Place" → "oreillysplace"
    """
    if not address:
        return ""
    
    val = str(address).strip()
    
    # Remove accents
    val = remove_accents(val)
    
    # Lowercase
    val = val.lower()
    
    # Remove all non-alphanumeric characters (including spaces, periods, commas, hyphens, apostrophes)
    val = re.sub(r"[^a-z0-9]", "", val)
    
    return val


def generate_combined_slug(
    country_code: str,
    state_code: str,
    city: str,
    hotel_name: str,
    address_line_1: str
) -> Optional[str]:
    """
    Generate slug from ALL components: country, state, city, name, AND address.
    Order: country - state - city - hotel_name - address_line_1
    
    Examples:
    "US", "TX", "San Antonio", "Hyatt", "1021 Hospitality Ln"
    → "us-tx-sanantonio-hyatt-1021hospitalityln"
    """
    # Skip if any required field is missing
    if not state_code or not state_code.strip():
        return None
    if not address_line_1 or not address_line_1.strip():
        return None
    
    # Normalize each component
    country_norm = normalize_address_slug(country_code)
    state_norm = normalize_address_slug(state_code)
    city_norm = normalize_address_slug(city)
    name_norm = normalize_address_slug(hotel_name)
    address_norm = normalize_address_slug(address_line_1)
    
    # Build slug parts
    parts = [country_norm, state_norm, city_norm, name_norm, address_norm]
    
    # Filter out any empty parts
    parts = [p for p in parts if p]
    
    # Join with hyphen
    slug = "-".join(parts)
    
    return slug


# =====================================================
# DATABASE OPERATIONS
# =====================================================

def test_connection():
    """Test database connection"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()
        print(f"✓ Database connection successful!")
        print(f"  PostgreSQL version: {version[0][:50]}...")
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        return False


def create_backup_table():
    """Create a backup of the web_scraped_hotels table"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # Check if backup already exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'test' 
                AND table_name = 'web_scraped_hotels_slug_backup'
            );
        """)
        
        backup_exists = cursor.fetchone()[0]
        
        if backup_exists:
            print("  Backup table already exists: test.web_scraped_hotels_slug_backup")
        else:
            # Create backup
            cursor.execute("""
                CREATE TABLE test.web_scraped_hotels_slug_backup AS 
                SELECT * FROM test.web_scraped_hotels;
            """)
            conn.commit()
            print("  ✓ Backup table created: test.web_scraped_hotels_slug_backup")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"  ✗ Backup failed: {e}")
        return False


def verify_data_quality():
    """Verify data quality and show statistics"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        print("\n" + "=" * 80)
        print("DATA QUALITY VERIFICATION")
        print("=" * 80)
        
        # Total records with all required fields including address
        cursor.execute("""
            SELECT COUNT(*) 
            FROM test.web_scraped_hotels
            WHERE name IS NOT NULL 
              AND state_code IS NOT NULL 
              AND city IS NOT NULL 
              AND country_code IS NOT NULL
              AND address_line_1 IS NOT NULL 
              AND address_line_1 != ''
        """)
        total_valid = cursor.fetchone()[0]
        print(f"✓ Total records with all required fields (including address): {total_valid:,}")
        
        # Records with special characters in address
        cursor.execute("""
            SELECT COUNT(*) 
            FROM test.web_scraped_hotels
            WHERE address_line_1 IS NOT NULL 
              AND address_line_1 != ''
              AND (
                address_line_1 LIKE '%.%' OR 
                address_line_1 LIKE '%,%' OR 
                address_line_1 LIKE '%''%' OR 
                address_line_1 LIKE '%&%' OR
                address_line_1 LIKE '%-%' OR
                address_line_1 LIKE '%é%' OR
                address_line_1 LIKE '%ñ%'
              );
        """)
        special_chars = cursor.fetchone()[0]
        print(f"✓ Records with special characters in address: {special_chars:,}")
        
        # Sample records with special characters
        cursor.execute("""
            SELECT address_line_1
            FROM test.web_scraped_hotels
            WHERE address_line_1 IS NOT NULL 
              AND address_line_1 != ''
              AND (
                address_line_1 LIKE '%.%' OR
                address_line_1 LIKE '%,%' OR
                address_line_1 LIKE '%-%'
              )
            LIMIT 10;
        """)
        
        samples = cursor.fetchall()
        if samples:
            print("\nSample addresses with special characters:")
            print("-" * 80)
            for (address,) in samples:
                slug = normalize_address_slug(address)
                print(f"  Original: {address}")
                print(f"  Slug:     {slug}")
                print()
        
        cursor.close()
        conn.close()
        return total_valid
        
    except Exception as e:
        print(f"✗ Verification failed: {e}")
        return 0


def add_slug_column():
    """Add web_slug column if it doesn't exist"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # Check if column exists
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_schema = 'test' 
              AND table_name = 'web_scraped_hotels' 
              AND column_name = 'web_slug';
        """)
        
        column_exists = cursor.fetchone() is not None
        
        if column_exists:
            print("  ✓ Column 'web_slug' already exists")
        else:
            cursor.execute("""
                ALTER TABLE test.web_scraped_hotels 
                ADD COLUMN web_slug VARCHAR(500);
            """)
            conn.commit()
            print("  ✓ Column 'web_slug' added successfully")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"  ✗ Failed to add column: {e}")
        return False


# =====================================================
# UPDATE SLUGS IN DATABASE
# =====================================================

def update_slugs():
    """Generate and update slugs for all records based on ALL fields"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        print("\n" + "=" * 80)
        print("GENERATING AND UPDATING SLUGS (COMBINED: COUNTRY-STATE-CITY-NAME-ADDRESS)")
        print("=" * 80)
        
        # Fetch records that have all required fields including address
        cursor.execute("""
            SELECT id, name, city, state_code, country_code, address_line_1
            FROM test.web_scraped_hotels
            WHERE name IS NOT NULL
              AND state_code IS NOT NULL
              AND city IS NOT NULL
              AND country_code IS NOT NULL
              AND address_line_1 IS NOT NULL
              AND address_line_1 != ''
        """)
        
        records = cursor.fetchall()
        print(f"Processing {len(records):,} records...")
        
        update_count = 0
        skip_count = 0
        error_count = 0
        
        for id, name, city, state_code, country_code, address_line_1 in records:
            try:
                # Generate slug from ALL fields: country, state, city, name, address
                slug = generate_combined_slug(country_code, state_code, city, name, address_line_1)
                
                if not slug:
                    skip_count += 1
                    continue
                
                # Update web_scraped_hotels
                cursor.execute("""
                    UPDATE test.web_scraped_hotels
                    SET web_slug = %s
                    WHERE id = %s;
                """, (slug, id))
                
                update_count += 1
                
                if update_count % 1000 == 0:
                    print(f"  Processed {update_count:,} records...")
                    conn.commit()  # Commit in batches
                
            except Exception as e:
                error_count += 1
                if error_count <= 5:
                    print(f"  ✗ Error processing id {id}: {e}")
        
        # Final commit
        conn.commit()
        
        print(f"\n✓ Update complete!")
        print(f"  Records updated: {update_count:,}")
        print(f"  Records skipped: {skip_count:,}")
        print(f"  Errors: {error_count}")
        
        cursor.close()
        conn.close()
        
        return update_count
        
    except Exception as e:
        print(f"✗ Update failed: {e}")
        return 0


def verify_results():
    """Verify the slug generation results"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        print("\n" + "=" * 80)
        print("VERIFICATION RESULTS")
        print("=" * 80)
        
        # Count total slugs
        cursor.execute("""
            SELECT 
                COUNT(*) as total_updated,
                COUNT(DISTINCT web_slug) as unique_slugs
            FROM test.web_scraped_hotels
            WHERE web_slug IS NOT NULL;
        """)
        
        total, unique = cursor.fetchone()
        duplicates = total - unique
        
        print(f"✓ Total records with slugs: {total:,}")
        print(f"✓ Unique slugs: {unique:,}")
        print(f"✓ Duplicate slugs: {duplicates:,}")
        
        # Show duplicate slugs if any
        if duplicates > 0:
            print(f"\n⚠ Warning: {duplicates:,} duplicate slugs found!")
            print("This is expected since different hotels may share the same address.")
            print("\nTop 10 most common duplicate slugs:")
            cursor.execute("""
                SELECT web_slug, COUNT(*) as count
                FROM test.web_scraped_hotels
                WHERE web_slug IS NOT NULL
                GROUP BY web_slug
                HAVING COUNT(*) > 1
                ORDER BY count DESC
                LIMIT 10;
            """)
            
            dup_results = cursor.fetchall()
            for slug, count in dup_results:
                print(f"  {slug}: {count} records")
        
        # Sample results
        print("\n" + "-" * 80)
        print("SAMPLE RESULTS (First 15 records)")
        print("-" * 80)
        
        cursor.execute("""
            SELECT name, city, state_code, country_code, address_line_1, web_slug
            FROM test.web_scraped_hotels
            WHERE web_slug IS NOT NULL
            ORDER BY id
            LIMIT 15;
        """)
        
        samples = cursor.fetchall()
        for name, city, state, country, address, slug in samples:
            print(f"Hotel: {name}")
            print(f"Location: {city}, {state}, {country}")
            print(f"Address: {address}")
            print(f"Slug: {slug}")
            print()
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"✗ Verification failed: {e}")


def show_test_cases():
    """Show test cases for slug generation"""
    print("\n" + "=" * 80)
    print("TESTING SLUG GENERATION FUNCTION")
    print("=" * 80)
    
    test_cases = [
        ("US", "TX", "San Antonio", "Éilan Hotel & Spa", "17103 La Cantera Parkway"),
        ("US", "NC", "Durham", "*Pristine Pad * King Bed Duke", "1234 Duke University Road"),
        ("CA", "ON", "Brampton", "Hyatt Place Toronto-brampton", "50 Corinne Court"),
        ("US", "CA", "Woodland Hills", "Courtyard Los Angeles", "1000 Main Street"),
        ("US", "TN", "Memphis", "Aloft Memphis Downtown", "102-40 Ditmars Boulevard"),
        ("MX", "QUE", "Queretaro", "Hyatt Centric Queretaro", "1000 N. Permeter Rd."),
        ("US", "TX", "WACO", "Towneplace Suites", "1021 Hospitality Ln"),
        ("US", "NY", "New York", "Hyatt Centric Wall Street", "006 Nalati East Street"),
    ]
    
    print("\nTest Cases (Country-State-City-Name-Address):")
    print("-" * 80)
    for country, state, city, name, address in test_cases:
        slug = generate_combined_slug(country, state, city, name, address)
        print(f"Input:")
        print(f"  Hotel: {name}")
        print(f"  Location: {city}, {state}, {country}")
        print(f"  Address: {address}")
        print(f"Output: {slug}")
        print("-" * 80)


def test_matching_query():
    """Test the matching between normalized addresses"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        print("\n" + "=" * 80)
        print("TESTING ADDRESS MATCHING")
        print("=" * 80)
        print("This shows how normalized slugs enable matching between tables")
        print("-" * 80)
        
        # Note: This assumes ingestion.hotel_masterfile table exists
        # If it doesn't exist, this will be skipped
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'ingestion' 
                AND table_name = 'hotel_masterfile'
            );
        """)
        
        table_exists = cursor.fetchone()[0]
        
        if not table_exists:
            print("  Note: ingestion.hotel_masterfile table not found")
            print("  Skipping matching test")
            cursor.close()
            conn.close()
            return
        
        # Show sample matches
        print("\nSample matched addresses (first 10):")
        print("-" * 80)
        cursor.execute("""
            SELECT DISTINCT 
                wb.address_line_1 as web_address,
                hm.address_line_1 as master_address,
                wb.web_slug as normalized_slug
            FROM test.web_scraped_hotels wb
            INNER JOIN ingestion.hotel_masterfile hm 
              ON wb.web_slug = hm.slug
            WHERE wb.web_slug IS NOT NULL
            LIMIT 10;
        """)
        
        matches = cursor.fetchall()
        if matches:
            for web_addr, master_addr, slug in matches:
                print(f"Web:    {web_addr}")
                print(f"Master: {master_addr}")
                print(f"Slug:   {slug}")
                print()
        else:
            print("  No matches found yet")
            print("  (Make sure to run the slug generation on both tables)")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"  Note: Could not test matching - {e}")


# =====================================================
# MAIN EXECUTION
# =====================================================

def main():
    """Main execution function"""
    print("=" * 80)
    print("WEB SCRAPED HOTELS - COMBINED SLUG GENERATOR")
    print("=" * 80)
    print("Generates slugs from: COUNTRY + STATE + CITY + NAME + ADDRESS")
    print("=" * 80)
    
    # Step 1: Test connection
    print("\n1. Testing database connection...")
    if not test_connection():
        print("\n✗ Cannot proceed without database connection!")
        return
    
    # Step 2: Show test cases
    show_test_cases()
    
    # Step 3: Verify data quality
    print("\n2. Verifying data quality...")
    total_records = verify_data_quality()
    
    if total_records == 0:
        print("\n✗ No valid records found to process!")
        return
    
    # Step 4: Ask for confirmation
    print("\n" + "=" * 80)
    print(f"Ready to process {total_records:,} records")
    print("This will:")
    print("  - Create a backup table")
    print("  - Add web_slug column (if not exists)")
    print("  - Generate slugs from: COUNTRY + STATE + CITY + NAME + ADDRESS")
    print("  - Update all records with combined normalized slugs")
    print("=" * 80)
    
    response = input("\nDo you want to proceed? (yes/no): ")
    
    if response.lower() != 'yes':
        print("\n✗ Operation cancelled by user")
        return
    
    # Step 5: Create backup
    print("\n3. Creating backup table...")
    create_backup_table()
    
    # Step 6: Add column
    print("\n4. Ensuring web_slug column exists...")
    if not add_slug_column():
        print("\n✗ Cannot proceed without web_slug column!")
        return
    
    # Step 7: Update slugs
    print("\n5. Generating and updating slugs...")
    records_updated = update_slugs()
    
    if records_updated == 0:
        print("\n✗ No records were updated!")
        return
    
    # Step 8: Verify results
    print("\n6. Verifying results...")
    verify_results()
    
    # Step 9: Test matching (optional)
    print("\n7. Testing address matching...")
    test_matching_query()
    
    print("\n" + "=" * 80)
    print("✓ PROCESS COMPLETED SUCCESSFULLY!")
    print("=" * 80)
    print(f"\nTotal records updated: {records_updated:,}")
    print("Backup table: test.web_scraped_hotels_slug_backup")
    print("\nSlug Format: country-state-city-name-address")
    print("Example: us-tx-sanantonio-hyatthotel-1021hospitalityln")
    print("\nYou can now use the 'web_slug' column for comprehensive matching!")
    print("\nExample matching query:")
    print("""
    SELECT wb.*, hm.*
    FROM test.web_scraped_hotels wb
    INNER JOIN ingestion.hotel_masterfile hm 
      ON wb.web_slug = hm.slug
    WHERE wb.web_slug IS NOT NULL;
    """)


if __name__ == "__main__":
    main()