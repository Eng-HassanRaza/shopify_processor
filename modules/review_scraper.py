"""Review scraper module"""
import requests
from bs4 import BeautifulSoup
import time
import random
import logging
from typing import List, Dict, Optional
from urllib.parse import urlparse, parse_qs

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
    
    def parse_review_data(self, soup: BeautifulSoup, url_rating: Optional[int] = None) -> List[Dict]:
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
                
                # Star rating - try to extract from HTML first, fallback to URL
                rating = self.extract_rating_from_html(section)
                if rating is None:
                    rating = url_rating  # Fallback to URL rating
            
                reviews.append({
                    'store_name': store_name,
                    'country': country,
                    'review_date': review_date,
                    'review_text': review_text,
                    'usage_duration': usage_duration,
                    'rating': rating
                })
            except Exception as e:
                logger.warning(f"Error parsing review section: {e}", exc_info=True)
                continue
        
        return reviews
    
    def extract_rating_from_url(self, url: str) -> Optional[int]:
        """
        Extract star rating from review URL
        
        Args:
            url: Review URL (e.g., https://apps.shopify.com/app/reviews?rating=1)
            
        Returns:
            Rating as integer (1-5) or None if not found
        """
        try:
            parsed = urlparse(url)
            
            # Check query parameter (e.g., ?rating=1)
            query_params = parse_qs(parsed.query)
            if 'rating' in query_params:
                rating = int(query_params['rating'][0])
                if 1 <= rating <= 5:
                    return rating
            
            # Check path segments (e.g., /reviews/1-star or /reviews?stars=1)
            path = parsed.path.lower()
            if '1-star' in path or '/1' in path:
                return 1
            elif '2-star' in path or '/2' in path:
                return 2
            elif '3-star' in path or '/3' in path:
                return 3
            elif '4-star' in path or '/4' in path:
                return 4
            elif '5-star' in path or '/5' in path:
                return 5
            
            # Check for stars parameter
            if 'stars' in query_params:
                rating = int(query_params['stars'][0])
                if 1 <= rating <= 5:
                    return rating
                    
        except Exception as e:
            logger.debug(f"Could not extract rating from URL {url}: {e}")
        
        return None
    
    def extract_rating_from_html(self, section) -> Optional[int]:
        """
        Extract star rating from HTML review section
        
        Args:
            section: BeautifulSoup element containing a review
            
        Returns:
            Rating as integer (1-5) or None if not found
        """
        try:
            # Method 1: Look for aria-label with rating (e.g., "4 out of 5 stars")
            aria_labels = section.find_all(attrs={'aria-label': True})
            for elem in aria_labels:
                aria_label = elem.get('aria-label', '').lower()
                # Match patterns like "4 out of 5 stars", "5 stars", "rated 4"
                import re
                match = re.search(r'(\d+)\s*(?:out of 5|stars|star)', aria_label)
                if match:
                    rating = int(match.group(1))
                    if 1 <= rating <= 5:
                        return rating
            
            # Method 2: Look for data attributes
            rating_attr = section.get('data-rating') or section.get('data-star-rating')
            if rating_attr:
                rating = int(rating_attr)
                if 1 <= rating <= 5:
                    return rating
            
            # Method 3: Look for SVG star elements (count filled stars)
            # Look for star icons - usually SVG elements with specific classes
            stars = section.find_all('svg', class_=lambda x: x and 'star' in str(x).lower())
            filled_stars = 0
            for star in stars:
                # Check if star is filled (has fill attribute that's not "none" or has specific class)
                fill = star.get('fill', '')
                classes = star.get('class', [])
                class_str = ' '.join(classes) if isinstance(classes, list) else str(classes)
                
                # Count filled stars (not transparent, not empty)
                if fill and fill.lower() not in ['none', 'transparent', '#fff', '#ffffff']:
                    filled_stars += 1
                elif 'filled' in class_str.lower() or 'active' in class_str.lower():
                    filled_stars += 1
            
            if 1 <= filled_stars <= 5:
                return filled_stars
            
            # Method 4: Look for text patterns (e.g., "★★★★☆" or "4/5")
            text_content = section.get_text()
            # Count star characters (★ = filled, ☆ = empty)
            filled_count = text_content.count('★')
            empty_count = text_content.count('☆')
            if filled_count > 0 and filled_count <= 5:
                return filled_count
            
            # Look for "X/5" pattern
            import re
            match = re.search(r'(\d+)\s*/\s*5', text_content)
            if match:
                rating = int(match.group(1))
                if 1 <= rating <= 5:
                    return rating
                    
        except Exception as e:
            logger.debug(f"Could not extract rating from HTML: {e}")
        
        return None
    
    def scrape_all_pages(self, review_url: str, max_pages: int = 0, start_page: int = 1, 
                         max_reviews: int = 0, progress_callback=None) -> List[Dict]:
        """
        Scrape all review pages from a review URL
        
        Args:
            review_url: The base review URL to scrape
            max_pages: Maximum pages to scrape (0 = no limit)
            start_page: Page number to start from (for resuming)
            max_reviews: Maximum number of reviews to scrape (0 = no limit)
            progress_callback: Callback function for progress updates
            
        Returns:
            List of review dictionaries
        """
        all_reviews = []
        page = start_page
        empty_pages = 0
        
        # Extract rating from URL (fallback if not found in HTML)
        url_rating = self.extract_rating_from_url(review_url)
        
        logger.info(f"Starting to scrape reviews from: {review_url}")
        if start_page > 1:
            logger.info(f"Resuming from page {start_page}")
        if max_reviews > 0:
            logger.info(f"Max reviews limit: {max_reviews}")
        if max_pages > 0:
            logger.info(f"Max pages limit: {max_pages}")
        if url_rating:
            logger.info(f"Rating from URL: {url_rating} stars")
        
        if progress_callback:
            progress_callback(f"Starting review scraping from page {start_page}...", start_page - 1, 0, 0)
        
        while True:
            # Check max_pages limit
            if max_pages > 0 and page > (start_page - 1 + max_pages):
                logger.info(f"Reached max_pages limit ({max_pages}), stopping")
                if progress_callback:
                    progress_callback(f"Reached max_pages limit, stopping at page {page-1}", page-1, page-1, len(all_reviews))
                break
            
            # Check max_reviews limit
            if max_reviews > 0 and len(all_reviews) >= max_reviews:
                logger.info(f"Reached max_reviews limit ({max_reviews}), stopping")
                if progress_callback:
                    progress_callback(f"Reached max_reviews limit ({max_reviews}), stopping at page {page-1}", page-1, page-1, len(all_reviews))
                break
            
            page_url = f"{review_url}&page={page}" if '?' in review_url else f"{review_url}?page={page}"
            
            logger.info(f"Scraping page {page}...")
            if progress_callback:
                progress_callback(f"Scraping page {page}...", page, 0, len(all_reviews))
            
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
            page_reviews = self.parse_review_data(soup, url_rating)
            
            if not page_reviews:
                empty_pages += 1
                if empty_pages >= 2:
                    logger.info("Two consecutive empty pages, stopping")
                    if progress_callback:
                        progress_callback("Finished scraping (no more reviews)", page, page, len(all_reviews))
                    break
            else:
                empty_pages = 0
                
                # Check if adding these reviews would exceed max_reviews limit
                if max_reviews > 0 and len(all_reviews) + len(page_reviews) > max_reviews:
                    # Add only up to the limit
                    remaining_slots = max_reviews - len(all_reviews)
                    if remaining_slots > 0:
                        all_reviews.extend(page_reviews[:remaining_slots])
                        logger.info(f"Reached max_reviews limit. Added {remaining_slots} reviews from page {page} (Total: {len(all_reviews)})")
                        if progress_callback:
                            progress_callback(f"Reached max_reviews limit ({max_reviews}) at page {page}", page, page, len(all_reviews))
                        break
                    else:
                        logger.info(f"Already reached max_reviews limit ({max_reviews}), stopping")
                        if progress_callback:
                            progress_callback(f"Already reached max_reviews limit ({max_reviews})", page-1, page-1, len(all_reviews))
                        break
                else:
                    all_reviews.extend(page_reviews)
                    logger.info(f"Found {len(page_reviews)} reviews on page {page} (Total: {len(all_reviews)})")
                    if progress_callback:
                        progress_callback(f"Found {len(page_reviews)} reviews on page {page}", page, page, len(all_reviews))
            
            page += 1
        
        final_page = page - 1  # Last page that was successfully scraped
        logger.info(f"Total reviews scraped: {len(all_reviews)} (from page {start_page} to {final_page})")
        
        # Determine stop reason for logging
        if max_reviews > 0 and len(all_reviews) >= max_reviews:
            logger.info(f"Stopped due to max_reviews limit ({max_reviews})")
        elif max_pages > 0 and final_page >= (start_page - 1 + max_pages):
            logger.info(f"Stopped due to max_pages limit ({max_pages})")
        elif empty_pages >= 2:
            logger.info("Stopped due to empty pages (no more reviews)")
        
        if progress_callback:
            if max_reviews > 0 and len(all_reviews) >= max_reviews:
                progress_callback(f"Reached max reviews limit ({max_reviews}). Found {len(all_reviews)} reviews", final_page, final_page, len(all_reviews))
            elif max_pages > 0 and final_page >= (start_page - 1 + max_pages):
                progress_callback(f"Reached max pages limit ({max_pages}). Found {len(all_reviews)} reviews", final_page, final_page, len(all_reviews))
            else:
                progress_callback(f"Scraping complete! Found {len(all_reviews)} reviews", final_page, final_page, len(all_reviews))
        
        return all_reviews

