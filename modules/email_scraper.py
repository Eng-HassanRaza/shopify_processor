"""Email scraper module"""
import asyncio
import aiohttp
import re
import html
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import logging
from typing import List, Set, Optional, Dict, Any

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
TIMEOUT = 15
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

class EmailScraper:
    def __init__(self, max_pages: int = 15, delay: float = 0.5, email_processor: Optional[Any] = None):
        self.max_pages = max_pages
        self.delay = delay
        self.email_processor = email_processor  # Kept for backward compatibility, not used
    
    def decode_cfemail(self, cf_str: str) -> Optional[str]:
        """Decode Cloudflare email obfuscation"""
        try:
            r = int(cf_str[:2], 16)
            out = ''.join([chr(int(cf_str[i:i+2], 16) ^ r) for i in range(2, len(cf_str), 2)])
            return out
        except:
            return None
    
    def extract_cfemails(self, soup: BeautifulSoup) -> Set[str]:
        """Extract emails from Cloudflare obfuscated elements"""
        emails = set()
        for el in soup.select("[data-cfemail]"):
            cf = el.get("data-cfemail")
            if cf:
                dec = self.decode_cfemail(cf)
                if dec and EMAIL_RE.fullmatch(dec):
                    emails.add(dec)
        return emails
    
    async def get_page(self, session: aiohttp.ClientSession, url: str):
        """Fetch page"""
        try:
            async with session.get(url, headers=HEADERS, timeout=TIMEOUT) as response:
                if response.status >= 400:
                    return None, url
                text = await response.text()
                return text, str(response.url)
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None, url
    
    def extract_emails_from_text(self, text: str) -> Set[str]:
        """Extract emails from plain text"""
        if not text:
            return set()
        
        text = html.unescape(text)
        text_alt = (text
                   .replace("(at)", "@").replace("[at]", "@").replace(" at ", "@")
                   .replace("(dot)", ".").replace("[dot]", ".").replace(" dot ", ".")
                   .replace(" AT ", "@").replace(" DOT ", "."))
        
        emails = set()
        emails |= set(re.findall(EMAIL_RE, text))
        emails |= set(re.findall(EMAIL_RE, text_alt))
        return emails
    
    def extract_emails_from_page(self, html_text: str, base_url: str) -> Set[str]:
        """Extract emails from a single page"""
        emails = set()
        if not html_text:
            return emails
        
        # Detect if content is XML (sitemap, etc.) and use appropriate parser
        is_xml = base_url.endswith('.xml') or html_text.strip().startswith('<?xml') or html_text.strip().startswith('<urlset')
        parser = "xml" if is_xml else "html.parser"
        soup = BeautifulSoup(html_text, parser)
        
        for a in soup.select('a[href^=mailto]'):
            href = a.get('href', '')
            email = href.split(':', 1)[1].split('?', 1)[0].strip()
            if EMAIL_RE.fullmatch(email):
                emails.add(email)
        
        emails |= self.extract_cfemails(soup)
        emails |= self.extract_emails_from_text(html_text)
        
        import json
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or "{}")
                def walk_json(obj):
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            if isinstance(v, (dict, list)):
                                walk_json(v)
                            elif isinstance(v, str) and EMAIL_RE.fullmatch(v):
                                emails.add(v)
                    elif isinstance(obj, list):
                        for item in obj:
                            walk_json(item)
                walk_json(data)
            except:
                pass
        
        return emails
    
    def get_target_pages(self, base_url: str) -> List[str]:
        """Get high-value pages for email extraction"""
        targets = [
            "/", "/contact", "/pages/contact", "/pages/contact-us", 
            "/pages/about", "/pages/about-us", "/about", "/about-us",
            "/policies/privacy-policy", "/policies/terms-of-service",
            "/policies/refund-policy", "/policies/shipping-policy",
            "/policies/contact-information", "/sitemap.xml"
        ]
        
        normalized = []
        for target in targets:
            full_url = urljoin(base_url, target)
            normalized.append(full_url)
        
        return normalized
    
    async def expand_from_sitemap(self, session: aiohttp.ClientSession, sitemap_url: str) -> List[str]:
        """Extract additional pages from sitemap"""
        html_text, final_url = await self.get_page(session, sitemap_url)
        if not html_text:
            return []
        
        soup = BeautifulSoup(html_text, "xml")
        urls = []
        
        for loc in soup.find_all("loc"):
            url = loc.get_text()
            if url and any(keyword in url.lower() for keyword in 
                          ["contact", "about", "policy", "privacy", "terms"]):
                urls.append(url)
        
        return urls[:20]
    
    async def scrape_emails(
        self, 
        store_url: str, 
        store_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Main function to scrape emails from a Shopify store
        
        Args:
            store_url: Store URL to scrape
            store_name: Optional store name for context in email processing
            
        Returns:
            Dictionary with processed emails and metadata:
            {
                'emails': List[str],           # Final filtered emails (all_unique)
                'primary': List[str],          # Domain + subdomain + legitimate third-party
                'secondary': List[str],        # AI-validated ambiguous third-party
                'categorized': Dict,           # Full categorization
                'stats': Dict                  # Statistics
            }
        """
        logger.info(f"Starting email extraction for: {store_url}")
        
        if not store_url.startswith(('http://', 'https://')):
            store_url = 'https://' + store_url
        
        parsed = urlparse(store_url)
        base_host = parsed.netloc
        
        target_pages = self.get_target_pages(store_url)
        sitemap_url = urljoin(store_url, "/sitemap.xml")
        
        async with aiohttp.ClientSession() as session:
            additional_pages = await self.expand_from_sitemap(session, sitemap_url)
            target_pages.extend(additional_pages)
            
            seen = set()
            unique_pages = []
            for page in target_pages:
                key = urlparse(page)._replace(query="", fragment="").geturl().rstrip("/")
                if key not in seen and urlparse(key).netloc == base_host:
                    seen.add(key)
                    unique_pages.append(key)
            
            unique_pages = unique_pages[:self.max_pages]
            
            logger.info(f"Will check {len(unique_pages)} pages")
            
            all_emails = set()
            visited = set()
            
            for i, page_url in enumerate(unique_pages):
                if page_url in visited:
                    continue
                
                visited.add(page_url)
                logger.info(f"Checking page {i+1}/{len(unique_pages)}: {page_url}")
                
                html_text, final_url = await self.get_page(session, page_url)
                if not html_text:
                    continue
                
                page_emails = self.extract_emails_from_page(html_text, final_url)
                all_emails.update(page_emails)
                
                if page_emails:
                    logger.info(f"Found {len(page_emails)} emails: {', '.join(page_emails)}")
                
                await asyncio.sleep(self.delay)
            
            # Basic filtering (remove obvious spam)
            filtered_emails = set()
            for email in all_emails:
                email_lower = email.lower()
                if not any(skip in email_lower for skip in [
                    '.png', '.jpg', '.jpeg', '.gif', '.css', '.js',
                    'example.com', 'test@', 'noreply@', 'no-reply@'
                ]):
                    filtered_emails.add(email)
            
            raw_emails = sorted(list(filtered_emails))
            logger.info(f"Total raw emails found: {len(raw_emails)}")
            
            # Return raw emails - AI extraction will be done in app.py
            # This keeps the scraper focused on scraping only
            return {
                'emails': raw_emails,  # Will be replaced by AI-extracted emails in app.py
                'raw_emails': raw_emails,
                'primary': raw_emails,
                'secondary': [],
                'categorized': {},
                'stats': {
                    'total_raw': len(raw_emails),
                    'total_unique': len(raw_emails),
                    'final_count': len(raw_emails)
                }
            }

