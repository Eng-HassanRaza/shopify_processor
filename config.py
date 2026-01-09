"""Configuration settings for Shopify Review Processor"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Base directory
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "shopify_processor" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Database
DATABASE_PATH = DATA_DIR / "shopify_processor.db"

# Server settings
HOST = "127.0.0.1"
PORT = 5001  # Changed from 5000 to avoid conflict with AirPlay
DEBUG = True

# Browser automation settings
BROWSER_HEADLESS = True  # Set to False to show browser
BROWSER_SLOW_MO = 500  # Delay between actions (ms)
BROWSER_TIMEOUT = 30000  # Page load timeout (ms)

# Scraping settings
REVIEW_SCRAPER_DELAY_MIN = 2.0
REVIEW_SCRAPER_DELAY_MAX = 5.0
EMAIL_SCRAPER_MAX_PAGES = 50  # Increased from 15 to allow more page discovery
EMAIL_SCRAPER_DELAY = 2.0  # Increased from 0.5s to 2s to reduce rate limiting (base delay)
EMAIL_SCRAPER_TIMEOUT = 30  # Timeout in seconds for page requests
EMAIL_SCRAPER_MAX_RETRIES = 3  # Number of retries for failed requests
EMAIL_SCRAPER_SITEMAP_LIMIT = 100  # Maximum URLs to extract from sitemap

# Email processing settings
EMAIL_USE_AI_VALIDATION = os.getenv('EMAIL_USE_AI_VALIDATION', 'false').lower() == 'true'  # Enable AI validation for ambiguous emails
EMAIL_AI_MIN_CONFIDENCE = float(os.getenv('EMAIL_AI_MIN_CONFIDENCE', '0.7'))  # Minimum confidence for AI-validated emails

# User agent for browser
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


