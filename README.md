# Shopify Review Processor

Unified web application for scraping Shopify app reviews, finding store URLs, and extracting emails.

## Features

- **Review Scraping**: Automatically scrape reviews from Shopify App Store pages
- **URL Finding**: Search Google and verify store URLs
- **Email Extraction**: Scrape emails from verified store websites
- **Progress Tracking**: SQLite database tracks all progress
- **Web Interface**: Clean, modern web UI for managing the workflow

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Install Playwright browsers:
```bash
playwright install chromium
```

## Usage

1. Start the application:
```bash
cd shopify_processor
python app.py
```

2. Open your browser to `http://127.0.0.1:5000`

3. Enter a Shopify App Review URL (e.g., `https://apps.shopify.com/app-name/reviews`)

4. Click "Start Scraping" to begin the workflow

5. For each store, click "Find URL" to search Google and select the correct store URL

6. Emails are automatically scraped after URL verification

7. Export data as JSON or CSV when complete

## Architecture

- **Database**: SQLite for persistent storage
- **Backend**: Flask web server with async support
- **Browser Automation**: Playwright for Google search
- **Email Scraping**: Async aiohttp for efficient scraping

## Configuration

Edit `config.py` to adjust:
- Server host/port
- Browser settings (headless mode, delays)
- Scraping limits and delays


