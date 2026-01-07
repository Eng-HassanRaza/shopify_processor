"""URL finder module using Playwright for Google search"""
import asyncio
import logging
import re
from typing import Optional, List
from playwright.async_api import async_playwright, Browser, Page
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

class URLFinder:
    def __init__(self, headless: bool = True, slow_mo: int = 500, timeout: int = 30000):
        self.headless = headless
        self.slow_mo = slow_mo
        self.timeout = timeout
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
    
    async def start_browser(self):
        """Start browser instance"""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo
        )
        self.page = await self.browser.new_page()
        await self.page.set_viewport_size({"width": 1920, "height": 1080})
        logger.info("Browser started")
    
    async def close_browser(self):
        """Close browser instance"""
        if self.browser:
            await self.browser.close()
            logger.info("Browser closed")
    
    def clean_url(self, url: str) -> str:
        """Clean URL to base URL"""
        try:
            parsed = urlparse(url)
            tracking_params = [
                'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
                'gclid', 'fbclid', 'srsltid', 'ref', 'source', 'campaign',
                'affiliate', 'partner', 'promo', 'discount', 'coupon'
            ]
            
            query_params = {}
            if parsed.query:
                from urllib.parse import parse_qs, urlencode
                params = parse_qs(parsed.query)
                for key, value in params.items():
                    if key not in tracking_params:
                        query_params[key] = value[0] if value else ''
            
            clean_parsed = parsed._replace(
                query=urlencode(query_params) if query_params else '',
                fragment=''
            )
            
            clean_url = urlunparse(clean_parsed)
            if clean_url.endswith('/') and len(clean_url) > 1:
                clean_url = clean_url.rstrip('/')
            
            return clean_url
        except Exception as e:
            logger.error(f"Error cleaning URL: {e}")
            return url
    
    async def open_google_search(self, store_name: str, country: str = ""):
        """Open Google search in browser for manual search"""
        if not self.page:
            await self.start_browser()
        
        # Clean store name - remove "shopify store" and date patterns if present
        clean_name = store_name
        # Remove common patterns like "shopify store", dates, etc.
        clean_name = re.sub(r'\s*shopify\s*store\s*', ' ', clean_name, flags=re.IGNORECASE)
        clean_name = re.sub(r'\s*\|\s*[A-Z]{2}\s*', ' ', clean_name)  # Remove "| BE" or similar
        clean_name = re.sub(r'\s*(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}', '', clean_name, flags=re.IGNORECASE)
        clean_name = re.sub(r'\s+\d{1,2}/\d{1,2}/\d{4}', '', clean_name)  # Remove date formats
        clean_name = ' '.join(clean_name.split())  # Clean up extra spaces
        
        # Use only the cleaned store name for search
        search_query = clean_name.strip()
        
        logger.info(f"Opening Google search for: {search_query}")
        
        try:
            search_url = f"https://www.google.com/search?q={search_query.replace(' ', '+')}"
            await self.page.goto(search_url, wait_until="networkidle", timeout=self.timeout)
            logger.info(f"Opened Google search in browser")
        except Exception as e:
            logger.error(f"Error opening Google search: {e}")
            raise
    
    async def get_page_url(self) -> Optional[str]:
        """Get current page URL"""
        if not self.page:
            return None
        try:
            return self.page.url
        except:
            return None
    
    async def navigate_to_url(self, url: str):
        """Navigate to a URL"""
        if not self.page:
            await self.start_browser()
        
        try:
            logger.info(f"Navigating to: {url}")
            await self.page.goto(url, wait_until="networkidle", timeout=self.timeout)
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Error navigating: {e}")

