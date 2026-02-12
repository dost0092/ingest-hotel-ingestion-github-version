"""
Configuration settings
"""
import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_ID = os.getenv("MODEL_ID", "openai/gpt-oss-120b")

# Database configuration
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT")),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD")
}

# Gemini API Configuration
GEMINI_CONFIG = {
    "project_id": os.getenv("GEMINI_PROJECT_ID"),
    "location": os.getenv("GEMINI_LOCATION"),
    "api_key": os.getenv("GEMINI_API_KEY"),
}

# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")