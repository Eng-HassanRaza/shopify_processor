"""Email scraper module"""
import asyncio
import aiohttp
import re
import html
import base64
import codecs
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
from collections import deque
import logging
from typing import List, Set, Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Improved email regex - more strict to avoid false positives like version@2.3.44
# Requires alphabetic TLD (not numbers) and proper domain structure
EMAIL_RE = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})*')

# Valid TLD keywords for validation
VALID_TLD_KEYWORDS = ['com', 'net', 'org', 'edu', 'gov', 'io', 'co', 'uk', 'ca', 'au', 'de', 'fr', 'es', 'it', 'nl', 'be', 'ch', 'at', 'jp', 'cn', 'in', 'br', 'mx', 'ar', 'za', 'ae', 'sa', 'sg', 'hk', 'nz', 'se', 'no', 'dk', 'fi', 'pl', 'cz', 'ie', 'pt', 'gr', 'ro', 'hu', 'info', 'biz', 'name', 'pro', 'xyz', 'website', 'site', 'email', 'tv', 'cc', 'ws', 'me', 'mobi', 'tel', 'asia', 'jobs', 'travel']

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

class EmailScraper:
    def __init__(self, max_pages: int = 50, delay: float = 0.5, timeout: int = 30, 
                 max_retries: int = 3, sitemap_limit: int = 100, email_processor: Optional[Any] = None):
        self.max_pages = max_pages
        self.base_delay = delay  # Base delay between requests
        self.current_delay = delay  # Current adaptive delay (increases with 429s)
        self.timeout = timeout
        self.max_retries = max_retries
        self.sitemap_limit = sitemap_limit
        self.email_processor = email_processor  # Kept for backward compatibility, not used
        
        # Rate limiting tracking
        self.consecutive_429_count = 0  # Track consecutive 429 errors
        self.max_consecutive_429 = 5  # Circuit breaker threshold
        self.circuit_open = False  # Circuit breaker state
        self.rate_limit_delay_multiplier = 2.0  # Multiply delay by this when rate limited
        self.max_delay = 60.0  # Maximum delay between requests (60 seconds)
    
    def normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication"""
        parsed = urlparse(url)
        # Remove query parameters and fragments
        normalized = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip('/') or '/',  # Normalize trailing slashes
            '',  # params
            '',  # query
            ''   # fragment
        ))
        return normalized
    
    def is_high_value_page(self, url: str) -> bool:
        """Check if page is likely to contain emails"""
        url_lower = url.lower()
        keywords = ['contact', 'about', 'privacy', 'terms', 'help', 'support', 
                   'team', 'careers', 'email', 'faq', 'policy', 'legal']
        return any(keyword in url_lower for keyword in keywords)
    
    def decode_cfemail(self, cf_str: str) -> Optional[str]:
        """Decode Cloudflare email obfuscation"""
        try:
            r = int(cf_str[:2], 16)
            out = ''.join([chr(int(cf_str[i:i+2], 16) ^ r) for i in range(2, len(cf_str), 2)])
            return out
        except:
            return None
    
    def decode_base64_email(self, text: str) -> Optional[str]:
        """Decode base64-encoded email"""
        try:
            decoded = base64.b64decode(text).decode('utf-8')
            if EMAIL_RE.fullmatch(decoded):
                return decoded
        except:
            pass
        return None
    
    def decode_entity_encoding(self, text: str) -> str:
        """Decode HTML entity encoding (&#64; = @, &#46; = .)"""
        # Replace common entity encodings
        text = text.replace('&#64;', '@').replace('&#064;', '@')
        text = text.replace('&#46;', '.').replace('&#046;', '.')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<').replace('&gt;', '>')
        return text
    
    def decode_rot13(self, text: str) -> str:
        """Decode ROT13 obfuscation"""
        try:
            return codecs.decode(text, 'rot13')
        except:
            return text
    
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
    
    def _handle_rate_limit(self, retry_after: Optional[int] = None):
        """Handle rate limiting by adjusting delay and tracking consecutive 429s"""
        self.consecutive_429_count += 1
        
        # Use Retry-After header if provided, otherwise use exponential backoff
        if retry_after:
            wait_time = min(float(retry_after), self.max_delay)
            logger.warning(f"Rate limited (429). Waiting {wait_time}s as specified by Retry-After header")
        else:
            # Exponential backoff: base delay * multiplier^consecutive_429s
            wait_time = min(self.current_delay * (self.rate_limit_delay_multiplier ** self.consecutive_429_count), self.max_delay)
            logger.warning(f"Rate limited (429). Adaptive delay increased to {wait_time:.2f}s (consecutive 429s: {self.consecutive_429_count})")
        
        # Update current delay for future requests
        self.current_delay = min(wait_time, self.max_delay)
        
        # Circuit breaker: if too many consecutive 429s, open circuit
        if self.consecutive_429_count >= self.max_consecutive_429:
            self.circuit_open = True
            logger.error(f"Circuit breaker OPENED: {self.consecutive_429_count} consecutive 429 errors. Maximum delay reached: {self.current_delay}s")
        
        return wait_time
    
    def _reset_rate_limit_tracking(self):
        """Reset rate limit tracking on successful request"""
        if self.consecutive_429_count > 0:
            logger.info(f"Rate limit tracking reset after successful request. Previous consecutive 429s: {self.consecutive_429_count}")
        self.consecutive_429_count = 0
        self.circuit_open = False
        # Gradually decrease delay back to base (but not too fast)
        if self.current_delay > self.base_delay:
            self.current_delay = max(self.base_delay, self.current_delay * 0.9)
    
    async def get_page(self, session: aiohttp.ClientSession, url: str) -> Tuple[Optional[str], str]:
        """Fetch page with retry logic and proper 429 handling"""
        # Check circuit breaker
        if self.circuit_open:
            logger.warning(f"Circuit breaker is OPEN. Waiting {self.current_delay}s before attempting {url}")
            await asyncio.sleep(self.current_delay)
            # Try to close circuit after waiting
            self.circuit_open = False
        
        for attempt in range(self.max_retries):
            try:
                async with session.get(url, headers=HEADERS, allow_redirects=True) as response:
                    # Check status before reading body
                    if response.status == 404:
                        logger.debug(f"Page not found (404): {url}")
                        # 404 is a valid response, reset rate limiting
                        self._reset_rate_limit_tracking()
                        return None, url
                    
                    # Special handling for 429 (Too Many Requests)
                    if response.status == 429:
                        # Check for Retry-After header
                        retry_after_header = response.headers.get('Retry-After')
                        retry_after = None
                        if retry_after_header:
                            try:
                                retry_after = int(retry_after_header)
                            except (ValueError, TypeError):
                                # Retry-After might be a date string, try to parse
                                try:
                                    from email.utils import parsedate_tz, mktime_tz
                                    retry_date = parsedate_tz(retry_after_header)
                                    if retry_date:
                                        retry_after = int(mktime_tz(retry_date) - time.time())
                                except:
                                    pass
                        
                        wait_time = self._handle_rate_limit(retry_after)
                        
                        # If circuit is open, don't retry immediately
                        if self.circuit_open:
                            logger.error(f"Circuit breaker OPEN. Stopping requests to {url} after {self.max_retries} attempts")
                            return None, url
                        
                        # Wait before retrying (use the wait_time from rate limit handler)
                        logger.warning(f"429 Too Many Requests for {url}, waiting {wait_time:.2f}s (attempt {attempt + 1}/{self.max_retries})")
                        await asyncio.sleep(wait_time)
                        continue
                    
                    # Handle other 4xx and 5xx errors (except 429 which is handled above)
                    if response.status >= 400:
                        if attempt < self.max_retries - 1:
                            wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                            logger.warning(f"HTTP {response.status} for {url}, retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries})")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"HTTP {response.status} for {url} after {self.max_retries} attempts")
                            # Don't reset rate limiting on errors (might still be rate limited)
                            return None, url
                    
                    # Success! Reset rate limit tracking on successful 2xx response
                    if 200 <= response.status < 300:
                        self._reset_rate_limit_tracking()
                    
                    # Read text inside the context manager
                    try:
                        # Use charset from response or default to utf-8
                        charset = response.charset or 'utf-8'
                        text = await response.text(encoding=charset, errors='replace')
                        final_url = str(response.url)
                        logger.debug(f"Successfully fetched {url} ({len(text)} bytes)")
                        return text, final_url
                    except UnicodeDecodeError as e:
                        logger.warning(f"Unicode decode error for {url}: {e}, trying with utf-8")
                        try:
                            text = await response.read()
                            text = text.decode('utf-8', errors='replace')
                            final_url = str(response.url)
                            return text, final_url
                        except Exception as e2:
                            logger.warning(f"Error reading response after decode retry for {url}: {e2}")
                            if attempt < self.max_retries - 1:
                                wait_time = 2 ** attempt
                                await asyncio.sleep(wait_time)
                                continue
                            return None, url
                    except Exception as e:
                        logger.warning(f"Error reading response text for {url}: {type(e).__name__} - {str(e)}")
                        if attempt < self.max_retries - 1:
                            wait_time = 2 ** attempt
                            await asyncio.sleep(wait_time)
                            continue
                        return None, url
                    
                    # If we got here, response was successfully read (2xx status)
                    # Rate limiting already reset above
                    
            except (asyncio.TimeoutError, aiohttp.ServerTimeoutError) as e:
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"Timeout for {url}, retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Timeout for {url} after {self.max_retries} attempts: {type(e).__name__}")
                    return None, url
                    
            except aiohttp.ClientError as e:
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"Client error for {url}: {type(e).__name__} - {str(e)}, retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Client error for {url} after {self.max_retries} attempts: {type(e).__name__} - {str(e)}")
                    return None, url
                    
            except Exception as e:
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"Unexpected error fetching {url}: {type(e).__name__} - {str(e)}, retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Unexpected error fetching {url} after {self.max_retries} attempts: {type(e).__name__} - {str(e)}")
                    return None, url
        
        logger.error(f"Failed to fetch {url} after {self.max_retries} attempts - no specific error captured")
        return None, url
    
    def extract_emails_from_text(self, text: str) -> Set[str]:
        """Extract emails from plain text with enhanced obfuscation handling"""
        if not text:
            return set()
        
        emails = set()
        
        # Decode HTML entities
        text = html.unescape(text)
        
        # Try entity encoding
        text_entity = self.decode_entity_encoding(text)
        
        # Try ROT13
        text_rot13 = self.decode_rot13(text)
        
        # Common obfuscation patterns
        text_alt = (text
                   .replace("(at)", "@").replace("[at]", "@").replace(" at ", "@")
                   .replace("(dot)", ".").replace("[dot]", ".").replace(" dot ", ".")
                   .replace(" AT ", "@").replace(" DOT ", ".")
                   .replace(" [at] ", "@").replace(" [dot] ", "."))
        
        # Extract from all variations
        for variant in [text, text_entity, text_rot13, text_alt]:
            found = re.findall(EMAIL_RE, variant)
            for email in found:
                # Additional validation: check TLD is not a number
                if self.is_valid_email(email):
                    emails.add(email.lower())
        
        return emails
    
    def is_valid_email(self, email: str) -> bool:
        """Validate email format more strictly"""
        if not EMAIL_RE.fullmatch(email):
            return False
        
        # Check that TLD is not a number (e.g., version@2.3.44)
        parts = email.split('@')
        if len(parts) != 2:
            return False
        
        domain = parts[1]
        tld_parts = domain.split('.')
        
        # Last part should be alphabetic TLD
        if tld_parts and tld_parts[-1].isdigit():
            return False
        
        # Domain should not be all numbers
        if domain.replace('.', '').isdigit():
            return False
        
        return True
    
    def extract_emails_from_page(self, html_text: str, base_url: str) -> Set[str]:
        """Extract emails from a single page with enhanced extraction"""
        emails = set()
        if not html_text:
            return emails
        
        # Detect if content is XML (sitemap, etc.) and use appropriate parser
        is_xml = base_url.endswith('.xml') or html_text.strip().startswith('<?xml') or html_text.strip().startswith('<urlset')
        parser = "xml" if is_xml else "html.parser"
        soup = BeautifulSoup(html_text, parser)
        
        # Extract from mailto links
        for a in soup.select('a[href^=mailto]'):
            href = a.get('href', '')
            email = href.split(':', 1)[1].split('?', 1)[0].strip()
            if self.is_valid_email(email):
                emails.add(email.lower())
        
        # Extract from data attributes
        for el in soup.select('[data-email], [data-contact]'):
            email_attr = el.get('data-email') or el.get('data-contact')
            if email_attr and self.is_valid_email(email_attr):
                emails.add(email_attr.lower())
        
        # Extract from title and aria-label attributes
        for el in soup.select('a[title], a[aria-label]'):
            attr_text = el.get('title') or el.get('aria-label', '')
            if attr_text:
                found = re.findall(EMAIL_RE, attr_text)
                for email in found:
                    if self.is_valid_email(email):
                        emails.add(email.lower())
        
        # Extract from href even if not mailto (sometimes emails are in href)
        for a in soup.select('a[href]'):
            href = a.get('href', '')
            # Check if href contains email pattern
            if '@' in href and not href.startswith('mailto:'):
                found = re.findall(EMAIL_RE, href)
                for email in found:
                    if self.is_valid_email(email):
                        emails.add(email.lower())
        
        # Cloudflare obfuscation
        emails |= self.extract_cfemails(soup)
        
        # Extract from page text
        emails |= self.extract_emails_from_text(html_text)
        
        # Extract from JSON-LD structured data
        import json
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string or "{}")
                def walk_json(obj):
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            if isinstance(v, (dict, list)):
                                walk_json(v)
                            elif isinstance(v, str) and self.is_valid_email(v):
                                emails.add(v.lower())
                    elif isinstance(obj, list):
                        for item in obj:
                            walk_json(item)
                walk_json(data)
            except:
                pass
        
        return emails
    
    def extract_footer_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Extract internal links from footer sections"""
        footer_links = []
        base_host = urlparse(base_url).netloc
        
        # Find footer elements
        footer_selectors = ['footer', '[role="contentinfo"]', '.footer', '#footer', 
                          '.site-footer', '#site-footer', '.main-footer', '#main-footer']
        
        footer_elements = []
        for selector in footer_selectors:
            footer_elements.extend(soup.select(selector))
        
        # Extract links from footer
        for footer in footer_elements:
            for link in footer.select('a[href]'):
                href = link.get('href', '')
                if not href:
                    continue
                
                # Convert relative to absolute
                full_url = urljoin(base_url, href)
                parsed = urlparse(full_url)
                
                # Only include same-domain internal links
                if parsed.netloc == base_host or not parsed.netloc:
                    # Filter for high-value pages
                    url_lower = full_url.lower()
                    keywords = ['contact', 'about', 'privacy', 'terms', 'help', 
                               'support', 'team', 'careers', 'email', 'faq', 
                               'policy', 'legal']
                    if any(keyword in url_lower for keyword in keywords):
                        footer_links.append(full_url)
        
        return footer_links
    
    def extract_internal_links(self, soup: BeautifulSoup, base_url: str, keywords: List[str]) -> List[str]:
        """Extract internal links containing specific keywords"""
        links = []
        base_host = urlparse(base_url).netloc
        
        # Avoid these paths (low email probability)
        skip_paths = ['/cart', '/checkout', '/account', '/search', '/products/', 
                      '/collections/', '/apps/', '/pages/product']
        
        for link in soup.select('a[href]'):
            href = link.get('href', '')
            if not href:
                continue
            
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
            
            # Only same-domain internal links
            if parsed.netloc == base_host or not parsed.netloc:
                url_lower = full_url.lower()
                
                # Skip product/cart pages
                if any(skip in url_lower for skip in skip_paths):
                    continue
                
                # Check if URL contains keywords
                if any(keyword in url_lower for keyword in keywords):
                    links.append(full_url)
        
        return links
    
    def get_target_pages(self, base_url: str) -> List[str]:
        """Get high-value pages for email extraction with expanded paths"""
        targets = [
            "/", "/contact", "/pages/contact", "/pages/contact-us", 
            "/pages/about", "/pages/about-us", "/about", "/about-us",
            "/help", "/support", "/faq", "/pages/help", "/pages/support", "/pages/faq",
            "/team", "/careers", "/careers/contact", "/pages/team", "/pages/careers",
            "/policies/privacy-policy", "/policies/terms-of-service",
            "/policies/refund-policy", "/policies/shipping-policy",
            "/policies/contact-information", "/policies/terms", "/policies/privacy",
            "/sitemap.xml"
        ]
        
        normalized = []
        for target in targets:
            full_url = urljoin(base_url, target)
            normalized.append(full_url)
        
        return normalized
    
    async def expand_from_sitemap(self, session: aiohttp.ClientSession, sitemap_url: str) -> List[str]:
        """Extract additional pages from sitemap with improved logic"""
        html_text, final_url = await self.get_page(session, sitemap_url)
        if not html_text:
            return []
        
        soup = BeautifulSoup(html_text, "xml")
        all_urls = []
        prioritized_urls = []
        
        # Extract all URLs
        for loc in soup.find_all("loc"):
            url = loc.get_text()
            if url:
                all_urls.append(url)
        
        # Prioritize URLs with email-relevant keywords
        keywords = ["contact", "about", "privacy", "terms", "help", "support", 
                   "team", "email", "policy", "legal", "faq"]
        
        for url in all_urls:
            url_lower = url.lower()
            if any(keyword in url_lower for keyword in keywords):
                prioritized_urls.append(url)
            elif 'policy' in url_lower or 'policies' in url_lower:
                prioritized_urls.append(url)
        
        # Combine: prioritized first, then others
        result = prioritized_urls + [u for u in all_urls if u not in prioritized_urls]
        
        # Limit to sitemap_limit
        return result[:self.sitemap_limit]
    
    async def discover_pages(self, session: aiohttp.ClientSession, store_url: str) -> List[Tuple[str, int]]:
        """Discover all pages to scrape with priority levels"""
        base_host = urlparse(store_url).netloc
        page_queue = []  # List of (url, priority) tuples
        seen = set()
        
        # Priority levels: 1 = high, 2 = medium, 3 = low
        # High priority: direct contact/about pages
        target_pages = self.get_target_pages(store_url)
        for page in target_pages:
            normalized = self.normalize_url(page)
            if normalized not in seen:
                seen.add(normalized)
                priority = 1 if self.is_high_value_page(page) else 2
                page_queue.append((page, priority))
        
        # Get sitemap URLs
        sitemap_url = urljoin(store_url, "/sitemap.xml")
        sitemap_pages = await self.expand_from_sitemap(session, sitemap_url)
        for page in sitemap_pages:
            normalized = self.normalize_url(page)
            if normalized not in seen and urlparse(page).netloc == base_host:
                seen.add(normalized)
                priority = 1 if self.is_high_value_page(page) else 2
                page_queue.append((page, priority))
        
        # Get footer links from homepage
        homepage_text, _ = await self.get_page(session, store_url)
        if homepage_text:
            soup = BeautifulSoup(homepage_text, "html.parser")
            footer_links = self.extract_footer_links(soup, store_url)
            for link in footer_links:
                normalized = self.normalize_url(link)
                if normalized not in seen and urlparse(link).netloc == base_host:
                    seen.add(normalized)
                    page_queue.append((link, 2))  # Medium priority
        
        # Follow links from high-value pages (1 level deep)
        high_value_pages = [url for url, pri in page_queue if pri == 1][:5]  # Limit to first 5
        for page_url in high_value_pages:
            page_text, _ = await self.get_page(session, page_url)
            if page_text:
                soup = BeautifulSoup(page_text, "html.parser")
                keywords = ['contact', 'email', 'support', 'help', 'team', 'about']
                internal_links = self.extract_internal_links(soup, page_url, keywords)
                for link in internal_links:
                    normalized = self.normalize_url(link)
                    if normalized not in seen and urlparse(link).netloc == base_host:
                        seen.add(normalized)
                        page_queue.append((link, 3))  # Low priority
        
        # Sort by priority (1 = high, 2 = medium, 3 = low)
        page_queue.sort(key=lambda x: x[1])
        
        # Limit to max_pages
        return page_queue[:self.max_pages]
    
    async def scrape_page(self, session: aiohttp.ClientSession, page_url: str) -> Tuple[Set[str], bool]:
        """Scrape a single page and return emails and success status"""
        try:
            html_text, final_url = await self.get_page(session, page_url)
            if not html_text:
                logger.warning(f"No HTML content returned for {page_url} - check get_page error logs above")
                return set(), False
            
            page_emails = self.extract_emails_from_page(html_text, final_url)
            if page_emails:
                logger.debug(f"Scraped {page_url}: found {len(page_emails)} emails")
            return page_emails, True
        except Exception as e:
            logger.error(f"Exception in scrape_page for {page_url}: {type(e).__name__} - {str(e)}", exc_info=True)
            return set(), False
    
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
            Dictionary with processed emails and metadata
        """
        logger.info(f"Starting email extraction for: {store_url}")
        
        if not store_url.startswith(('http://', 'https://')):
            store_url = 'https://' + store_url
        
        parsed = urlparse(store_url)
        base_host = parsed.netloc
        
        stats = {
            'pages_discovered': 0,
            'pages_scraped': 0,
            'pages_failed': 0,
            'pages_with_emails': 0
        }
        
        # Create session with timeout configuration
        timeout = aiohttp.ClientTimeout(total=self.timeout, connect=10, sock_read=self.timeout)
        connector = aiohttp.TCPConnector(
            limit=20, 
            limit_per_host=10, 
            ssl=False,  # Allow unverified SSL for some stores
            force_close=False,  # Keep connections alive
            enable_cleanup_closed=True  # Clean up closed connections
        )
        
        logger.info(f"Initializing session with timeout={self.timeout}s, max_retries={self.max_retries}, max_pages={self.max_pages}")
        
        async with aiohttp.ClientSession(timeout=timeout, connector=connector, headers=HEADERS) as session:
            # Discover all pages with priorities
            try:
                page_queue = await self.discover_pages(session, store_url)
                stats['pages_discovered'] = len(page_queue)
                
                logger.info(f"Discovered {len(page_queue)} pages to scrape")
                
                if not page_queue:
                    logger.warning(f"No pages discovered for {store_url}. This might indicate an issue with the store URL or network connectivity.")
                
                all_emails = set()
                visited = set()
                
                # Reset rate limiting at start of scraping session
                self.current_delay = self.base_delay
                self.consecutive_429_count = 0
                self.circuit_open = False
                
                # Process pages in priority order
                for i, (page_url, priority) in enumerate(page_queue):
                    normalized = self.normalize_url(page_url)
                    if normalized in visited:
                        continue
                    
                    visited.add(normalized)
                    priority_label = ['high', 'medium', 'low'][priority - 1]
                    
                    # Check if circuit breaker is open
                    if self.circuit_open:
                        logger.error(f"Circuit breaker OPEN. Stopping page scraping. Scraped {i}/{len(page_queue)} pages so far.")
                        break
                    
                    logger.info(f"Checking page {i+1}/{len(page_queue)} [{priority_label} priority]: {page_url} (current delay: {self.current_delay:.2f}s)")
                    
                    page_emails, success = await self.scrape_page(session, page_url)
                    
                    if success:
                        stats['pages_scraped'] += 1
                        if page_emails:
                            stats['pages_with_emails'] += 1
                            logger.info(f"Found {len(page_emails)} emails: {', '.join(page_emails)}")
                    else:
                        stats['pages_failed'] += 1
                        logger.warning(f"Failed to scrape page: {page_url}")
                    
                    all_emails.update(page_emails)
                    
                    # Use adaptive delay (increases if rate limited, decreases on success)
                    # Only wait if not the last page
                    if i < len(page_queue) - 1:
                        logger.debug(f"Waiting {self.current_delay:.2f}s before next request (adaptive delay)")
                        await asyncio.sleep(self.current_delay)
            except Exception as e:
                logger.error(f"Error during page discovery or scraping: {type(e).__name__} - {str(e)}", exc_info=True)
            
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
            logger.info(f"Scraping stats: {stats}")
            
            # Return raw emails - AI extraction will be done in app.py
            return {
                'emails': raw_emails,
                'raw_emails': raw_emails,
                'primary': raw_emails,
                'secondary': [],
                'categorized': {},
                'stats': {
                    'total_raw': len(raw_emails),
                    'total_unique': len(raw_emails),
                    'final_count': len(raw_emails),
                    'pages_discovered': stats['pages_discovered'],
                    'pages_scraped': stats['pages_scraped'],
                    'pages_failed': stats['pages_failed'],
                    'pages_with_emails': stats['pages_with_emails']
                }
            }
