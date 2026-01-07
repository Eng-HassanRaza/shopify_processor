"""Review scraper module"""
import requests
from bs4 import BeautifulSoup
import time
import random
import logging
from typing import List, Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class ReviewScraper:
    def __init__(self):
        self.session = requests.Session()
        self.base_url = "https://apps.shopify.com"
        
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
        }
        self.session.headers.update(self.headers)
    
    def extract_app_name(self, url: str) -> str:
        """Extract app name from Shopify App Store URL"""
        try:
            path = urlparse(url).path
            parts = [p for p in path.split('/') if p]
            if 'reviews' in parts:
                idx = parts.index('reviews')
                if idx > 0:
                    return parts[idx - 1]
            return 'unknown_app'
        except:
            return 'unknown_app'
    
    def get_random_delay(self, min_delay: float = 2.0, max_delay: float = 5.0) -> float:
        return random.uniform(min_delay, max_delay)
    
    def make_request(self, url: str, max_retries: int = 3) -> Optional[requests.Response]:
        for attempt in range(max_retries):
            try:
                delay = self.get_random_delay()
                logger.info(f"Waiting {delay:.2f}s before request...")
                time.sleep(delay)
                
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                logger.info(f"Fetched: {url}")
                return response
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(self.get_random_delay(5, 10))
                else:
                    logger.error(f"Failed after {max_retries} attempts")
                    return None
    
    def parse_review_data(self, soup: BeautifulSoup) -> List[Dict]:
        reviews = []
        
        # Try multiple selectors to find review sections
        review_sections = soup.find_all('div', {'data-merchant-review': True})  # Primary selector
        
        if not review_sections:
            review_sections = soup.find_all('div', class_=lambda x: x and ('lg:tw-grid-cols-4' in str(x) and 'tw-gap-xs' in str(x)))
        
        if not review_sections:
            review_sections = soup.find_all('div', class_=lambda x: x and ('lg:tw-row-span-2' in str(x) or 'tw-order-1' in str(x)))
        
        if not review_sections:
            review_sections = soup.find_all('div', {'data-review-id': True})
        
        if not review_sections:
            review_sections = soup.find_all(['article', 'section'], class_=lambda x: x and 'review' in str(x).lower())
        
        logger.info(f"Found {len(review_sections)} review sections")
        
        for section in review_sections:
            try:
                # Store name - try multiple approaches
                store_name = "Unknown Store"
                store_name_elem = section.find('span', class_=lambda x: x and 'tw-overflow-hidden' in str(x) and 'tw-text-ellipsis' in str(x))
                if store_name_elem:
                    store_name = store_name_elem.get_text(strip=True)
                else:
                    store_name_elem = section.find('a', href=lambda x: x and '/stores/' in str(x))
                    if store_name_elem:
                        store_name = store_name_elem.get_text(strip=True)
                    else:
                        # Fallback: look for any link that might contain a store name
                        links = section.find_all('a')
                        for link in links:
                            href = link.get('href', '')
                            if '/stores/' in href:
                                store_name = link.get_text(strip=True)
                                break
                
                if not store_name or store_name == "Unknown Store":
                    logger.warning(f"Could not extract store name from section: {section.prettify()[:200]}")
                    continue
                
                # Country
                country = ""
                country_elem = section.find('div', string=lambda x: x and len(x.strip()) > 2 and not ('year' in x.lower() or 'month' in x.lower() or 'day' in x.lower()))
                if country_elem:
                    country = country_elem.get_text(strip=True)
                else:
                    # Look for flag emoji or country text in spans
                    spans = section.find_all('div', class_=lambda x: x and 'tw-text-body-xs' in str(x))
                    for span in spans:
                        text = span.get_text(strip=True)
                        if len(text) > 2 and not ('year' in text.lower() or 'month' in text.lower() or 'day' in text.lower() or 'ago' in text.lower() or 'replied' in text.lower()):
                            country = text
                            break
                
                # Review text
                review_text = ""
                review_text_elem = section.find('div', {'data-truncate-content-copy': True})
                if review_text_elem:
                    review_text = review_text_elem.get_text(strip=True)
                else:
                    review_text_elem = section.find('p', class_=lambda x: x and 'tw-break-words' in str(x))
                    if review_text_elem:
                        review_text = review_text_elem.get_text(strip=True)
                    else:
                        review_text_elem = section.find('div', class_=lambda x: x and 'tw-text-body-md' in str(x) and 'tw-text-fg-secondary' in str(x))
                        if review_text_elem:
                            review_text = review_text_elem.get_text(strip=True)
                
                # Review date
                date_elem = section.find('time')
                if not date_elem:
                    date_elem = section.find('div', class_=lambda x: x and 'tw-text-body-xs' in str(x) and 'tw-text-fg-tertiary' in str(x) and ('October' in x or 'November' in x or 'December' in x or 'January' in x or 'February' in x or 'March' in x or 'April' in x or 'May' in x or 'June' in x or 'July' in x or 'August' in x or 'September' in x))
                review_date = date_elem.get('datetime') if date_elem and date_elem.get('datetime') else (date_elem.get_text(strip=True) if date_elem else "")
                
                # Usage duration
                usage_duration = ""
                usage_elem = section.find('div', string=lambda x: x and ('month' in x.lower() or 'year' in x.lower() or 'day' in x.lower() or 'ago' in x.lower()))
                if usage_elem:
                    usage_duration = usage_elem.get_text(strip=True)
                else:
                    # Look for usage duration in other divs
                    divs = section.find_all('div', class_=lambda x: x and 'tw-text-body-xs' in str(x) and 'tw-text-fg-tertiary' in str(x))
                    for div in divs:
                        text = div.get_text(strip=True)
                        if 'using the app' in text.lower():
                            usage_duration = text
                            break
            
                reviews.append({
                    'store_name': store_name,
                    'country': country,
                    'review_date': review_date,
                    'review_text': review_text,
                    'usage_duration': usage_duration
                })
            except Exception as e:
                logger.warning(f"Error parsing review section: {e}", exc_info=True)
                continue
        
        return reviews
    
    def scrape_all_pages(self, review_url: str, max_pages: int = 0, progress_callback=None) -> List[Dict]:
        all_reviews = []
        page = 1
        empty_pages = 0
        
        logger.info(f"Starting to scrape reviews from: {review_url}")
        
        if progress_callback:
            progress_callback(f"Starting review scraping...", 0, 0, 0)
        
        while True:
            if max_pages > 0 and page > max_pages:
                break
            
            page_url = f"{review_url}&page={page}" if '?' in review_url else f"{review_url}?page={page}"
            
            logger.info(f"Scraping page {page}...")
            if progress_callback:
                progress_callback(f"Scraping page {page}...", page, page, len(all_reviews))
            
            response = self.make_request(page_url)
            
            if not response:
                empty_pages += 1
                if empty_pages >= 2:
                    logger.info("Two consecutive empty pages, stopping")
                    if progress_callback:
                        progress_callback("Finished scraping (no more pages)", page, page, len(all_reviews))
                    break
                page += 1
                continue
            
            soup = BeautifulSoup(response.text, 'html.parser')
            page_reviews = self.parse_review_data(soup)
            
            if not page_reviews:
                empty_pages += 1
                if empty_pages >= 2:
                    logger.info("Two consecutive empty pages, stopping")
                    if progress_callback:
                        progress_callback("Finished scraping (no more reviews)", page, page, len(all_reviews))
                    break
            else:
                empty_pages = 0
                all_reviews.extend(page_reviews)
                logger.info(f"Found {len(page_reviews)} reviews on page {page} (Total: {len(all_reviews)})")
                if progress_callback:
                    progress_callback(f"Found {len(page_reviews)} reviews on page {page}", page, page, len(all_reviews))
            
            page += 1
        
        logger.info(f"Total reviews scraped: {len(all_reviews)}")
        if progress_callback:
            progress_callback(f"Scraping complete! Found {len(all_reviews)} reviews", page-1, page-1, len(all_reviews))
        return all_reviews

