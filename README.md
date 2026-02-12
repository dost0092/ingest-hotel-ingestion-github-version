# web-scraper-atomic-solution — Hotel Extraction & ingestion Pipeline

A modular FastAPI service and scraping toolkit for discovering Hilton hotel locations and extracting detailed hotel information (amenities, policies, addresses), with LLM-powered web context generation and structured pet-policy extraction.

Built for automation, deduplication (content hashing), and PostgreSQL-backed persistence.

---

## ✨ Features

- 🔍 **Hotel Discovery** — Scrape Hilton hotel locations worldwide with optional country filtering
- 📊 **Rich Data Extraction** — Extract amenities, policies, addresses, and pet-friendly attributes
- 🤖 **Anti-Bot Protection** — Uses `undetected-chromedriver` to bypass bot detection
- 🗄️ **PostgreSQL Integration** — Structured storage with indexing, hashing, and JSONB attributes
- 🧬 **LLM Integration** — Web context generation and pet attribute extraction using OpenRouter/OpenAI
- ⚡ **FastAPI Backend** — High-performance async API with background job queueing
- 🔗 **Content Hashing** — Prevents duplicate scraping by detecting unchanged content
- 📦 **Docker Ready** — Fully containerized for easy deployment

---

## 📁 Project Structure

```
web-scraper-atomic/
│
├── config/                 # Configuration management
│   └── settings.py         # Environment variables, DB config, API keys
│
├── context_extraction/     # Core extraction logic
│   └── hotel_extraction.py # Main pipeline orchestrator (9 steps)
│
├── db/                     # Database layer
│   ├── db_connection.py    # PostgreSQL connection pooling
│   └── operations.py       # CRUD operations for raw/web_context/pet_attributes
│
├── helper/                 # Utility helpers
│   └── (helper modules)    # Logging, validation, formatters
│
├── llm/                    # LLM integration modules
│   ├── models.py           # Pydantic models (NullableField, PetInformation)
│   ├── pet_attribute_extractor.py  # Structured pet policy extraction
│   └── web_context_generator.py    # Compact web context generation
│
├── scraping/               # Web scraping modules
│   └── hilton_scraper.py   # Selenium + undetected-chromedriver
│
├── url/                    # URL management
│   └── (url utilities)     # URL validation, normalization
│
├── utils/                  # Core utilities
│   └── context_hashing.py  # Content hash generation (SHA-256)
│
├── main.py                 # FastAPI application entry point
├── .env                    # Environment variables (not in repo)
├── .gitignore              # Git ignore rules
├── requirements.txt        # Python dependencies
└── README.md               # This file
```

---

## 🔧 How It Works — The 9-Step Pipeline

The extraction pipeline in `context_extraction/hotel_extraction.py` orchestrates the entire workflow:

### **Step 1: Scrape Hotel Page**
- **Module:** `scraping/hilton_scraper.py`
- **Function:** Uses Selenium with `undetected-chromedriver` to bypass bot detection
- **Output:** Raw HTML and parsed data (name, description, address, phone, amenities, policies)

### **Step 2: Generate Content Hash**
- **Module:** `utils/context_hashing.py`
- **Function:** Creates md5 hash of scraped content for deduplication
- **Purpose:** Detects if hotel page has changed since last scrape

### **Step 3: Save Raw Extraction**
- **Module:** `db/operations.py` → `save_raw_hash()`
- **Function:** Stores raw scraped data in hash form in PostgreSQL
- **Returns:** Database record ID for subsequent steps

### **Step 4: Generate Web Context**
- **Module:** `llm/web_context_generator.py`
- **Function:** Calls OpenRouter/OpenAI LLM to generate compact, structured summary
- **Output:** Clean, formatted text block with hotel details
- **Example:**
  ```
  Hotel Name: Hilton Anchorage
  Description: Located in the heart of downtown...
  Address: 500 West Third Avenue, Anchorage, Alaska, 99501, USA
  Phone: +1 907-272-7411
  Amenities & Facilities: Indoor pool, Fitness center, Pet-friendly rooms...
  Parking Policy: Self-parking (on-site) – $25.00 per day...
  Pets Policy: Pets allowed – Yes; Deposit – $75.00 non-refundable fee...
  ```

### **Step 5: Save Web Context**
- **Module:** `db/operations.py` → `save_web_context()`
- **Function:** Stores LLM-generated context linked to record ID

### **Step 6: Extract Pet Attributes**
- **Module:** `llm/pet_attribute_extractor.py`
- **Function:** Uses LLM to extract structured pet policy data
- **Output:** Pydantic-validated JSON with status (`present`/`not_mentioned`) and confidence scores
- **Example:**
  ```json
  {
    "pet_information": {
      "is_pet_friendly": {"status": "present", "value": true},
      "has_pet_deposit": {"status": "present", "value": true},
      "pet_deposit_amount": {"status": "present", "value": 75.0},
      "is_deposit_refundable": {"status": "present", "value": false},
      "max_weight_lbs": {"status": "present", "value": 75}
    },
    "confidence_scores": {
      "is_pet_friendly": 1.0,
      "pet_deposit_amount": 1.0,
      "max_weight_lbs": 1.0
    }
  }
  ```

### **Step 7: Save Pet Attributes**
- **Module:** `db/operations.py` → `save_pet_attributes()`
- **Function:** Stores structured pet policy as JSONB in PostgreSQL

### **Step 8: Generate Web Slug**
- **Module:** `context_extraction/hotel_extraction.py`
- **Function:** Creates URL-friendly slug from hotel name (e.g., `us-ak-anchorage-hiltonanchorage-500westthirdavenue`)

### **Step 9: Update Database with Slug**
- **Module:** `db/operations.py` → `update_web_slug()`
- **Function:** Finalizes record with web slug for frontend routing

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.9+**
- **PostgreSQL 13+**
- **Google Chrome** (for Selenium)
- **API Keys:**
  - OpenRouter API key (or OpenAI-compatible endpoint)
  - Optional: Google Gemini

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/web-scraper-atomic.git
cd web-scraper-atomic

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Environment Configuration

Create a `.env` file in the project root:

```env
# Database Configuration
DB_HOST=localhost
DB_PORT=5432
DB_NAME=hotel_scraper
DB_USER=postgres
DB_PASSWORD=your_password

# Browser Configuration
HEADLESS=true
RESTART_INTERVAL=100

# LLM Configuration
OPENROUTER_API_KEY=your_openrouter_key
MODEL_ID=openai/gpt-4

# Application Configuration
HOST=0.0.0.0
PORT=8000
DEBUG=false
```

### Database Setup

```sql
-- Create database
CREATE DATABASE hotel_scraper;

-- Connect to database and create tables
-- (Run migrations or schema from db/ module)
```

### Run the Application

```bash
# Start FastAPI server
python main.py

# API will be available at http://localhost:8000
# Swagger docs at http://localhost:8000/docs
```

---

## 📊 Module Functions Explained

### `config/settings.py`
- Loads environment variables using `python-dotenv`
- Provides centralized configuration for DB, LLM, and browser settings

### `context_extraction/hotel_extraction.py`
- **Main function:** `extract_hotel_data(url: str) -> dict`
- Orchestrates all 9 pipeline steps
- Handles errors gracefully with logging at each step
- Returns complete extraction result with record ID

### `db/db_connection.py`
- **Function:** `get_db_connection()`
- Manages PostgreSQL connection pool using `psycopg2`
- Ensures thread-safe connections

### `db/operations.py`
- **`save_raw_extraction(url, data, content_hash)`** — Inserts raw scraped data
- **`save_web_context(record_id, context)`** — Updates record with LLM context
- **`save_pet_attributes(record_id, attributes)`** — Stores JSONB pet policy
- **`update_web_slug(record_id, slug)`** — Finalizes record with slug
- **`get_extraction_by_hash(content_hash)`** — Checks for duplicate content

### `llm/models.py`
- Defines Pydantic models for validation:
  - `NullableField[T]` — Generic field with `status` and `value`
  - `PetInformation` — Comprehensive pet policy schema
  - `PetExtractionResult` — Contains pet info + confidence scores

### `llm/pet_attribute_extractor.py`
- **Function:** `extract_pet_attributes(web_context: str) -> PetExtractionResult`
- Sends web context to LLM with structured prompt
- Validates response against Pydantic schema
- Returns JSON with status flags and confidence scores

### `llm/web_context_generator.py`
- **Function:** `generate_web_context(raw_data: dict) -> str`
- Converts raw scraped data into clean, readable format
- Uses LLM to normalize and structure information
- Returns formatted text block for database storage

### `scraping/hilton_scraper.py`
- **Function:** `scrape_hilton_hotel(url: str) -> dict`
- Uses Selenium WebDriver with `undetected-chromedriver`
- Extracts hotel name, description, address, phone, amenities, policies
- Handles dynamic content and JavaScript-rendered elements
- Returns structured dictionary of scraped data

### `utils/context_hashing.py`
- **Function:** `generate_content_hash(content: str) -> str`
- Creates SHA-256 hash of content for deduplication
- Ensures consistent hashing for duplicate detection

---

## 📝 Sample Run Output

```
2026-02-04 16:33:38,407 - main - INFO - Starting hotel extraction: https://www.hilton.com/en/hotels/ancahhf-hilton-anchorage/
2026-02-04 16:33:41,988 - context_extraction.hotel_extraction - INFO - Step 1: Scraping hotel page...
2026-02-04 16:33:43,842 - undetected_chromedriver.patcher - INFO - patching driver executable
2026-02-04 16:34:37,427 - db.operations - INFO - Saved raw extraction with ID: 4
2026-02-04 16:34:53,609 - llm.web_context_generator - INFO - Web context generated successfully
2026-02-04 16:34:54,091 - db.operations - INFO - Saved web context for record ID: 4
2026-02-04 16:35:03,623 - db.operations - INFO - Saved pet attributes for record ID: 4
2026-02-04 16:35:04,350 - db.operations - INFO - Updated web slug for record ID: 4
2026-02-04 16:35:04,650 - context_extraction.hotel_extraction - INFO - Extraction completed successfully
```

---

## ⚠️ Known Issues & Fixes

### Pydantic Generic Warning

```
GenericBeforeBaseModelWarning: Classes should inherit from `BaseModel` before generic classes
```

**Fix:** In `llm/models.py`, change:
```python
class NullableField(Generic[T], BaseModel):
```
to:
```python
class NullableField(BaseModel, Generic[T]):
```

### Browser Detection

If scraping fails with bot detection:
- Toggle `HEADLESS=false` in `.env`
- Add realistic browser flags in `scraping/hilton_scraper.py`
- Use residential proxies if needed

### LLM API Errors

- Verify `OPENROUTER_API_KEY` is valid
- Check model availability: `MODEL_ID=openai/gpt-4`
- Monitor rate limits and adjust retry logic

---

## 🐳 Docker Deployment

```bash
# Build image
docker build -t web-scraper-atomic .

# Run with docker-compose
docker-compose up -d

# Check logs
docker-compose logs -f
```

---

## 🧪 Testing

```bash
# Run unit tests
pytest tests/

# Run integration tests
pytest tests/integration/

# Check coverage
pytest --cov=.
```

---

## 📈 Performance Considerations

- **Scraping:** ~50 seconds per hotel (including LLM calls)
- **Database:** Indexed on `url`, `content_hash`, `web_slug`
- **Deduplication:** Hash-based detection prevents redundant scraping
- **Concurrency:** FastAPI background tasks allow parallel extractions

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---


**Built with ❤️ for hotel data extraction automation**
