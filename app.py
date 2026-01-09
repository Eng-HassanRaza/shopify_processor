"""Main Flask application"""
from flask import Flask, render_template, jsonify, request, Response
from flask_cors import CORS
import logging
import threading
import asyncio
import requests
import time
from config import HOST, PORT, DEBUG, DATABASE_PATH, EMAIL_SCRAPER_MAX_PAGES, EMAIL_SCRAPER_DELAY, EMAIL_SCRAPER_TIMEOUT, EMAIL_SCRAPER_MAX_RETRIES, EMAIL_SCRAPER_SITEMAP_LIMIT
from database import Database
from modules.review_scraper import ReviewScraper
from modules.url_finder import URLFinder
from modules.email_scraper import EmailScraper
from modules.ai_url_selector import AIURLSelector
from modules.ai_email_extractor import AIEmailExtractor
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# Allow all origins for extension access
# Allow all origins for extension access
CORS(app, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "PUT", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

db = Database(str(DATABASE_PATH))
review_scraper = ReviewScraper()
url_finder = URLFinder(headless=False)  # Visible browser for manual search

# Initialize AI Email Extractor
try:
    ai_email_extractor = AIEmailExtractor()
    logger.info("AI Email Extractor initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize AI Email Extractor: {e}. Email extraction will fail without OpenAI API key.")
    ai_email_extractor = None

# Initialize Email Scraper with config values
email_scraper = EmailScraper(
    max_pages=EMAIL_SCRAPER_MAX_PAGES,
    delay=EMAIL_SCRAPER_DELAY,
    timeout=EMAIL_SCRAPER_TIMEOUT,
    max_retries=EMAIL_SCRAPER_MAX_RETRIES,
    sitemap_limit=EMAIL_SCRAPER_SITEMAP_LIMIT,
    email_processor=None
)

# Initialize AI URL Selector
try:
    ai_selector = AIURLSelector()
    logger.info("AI URL Selector initialized successfully")
except Exception as e:
    logger.warning(f"Failed to initialize AI URL Selector: {e}. AI features will be disabled.")
    ai_selector = None

# Add CORS headers to all responses for extension access
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/data')
def data_page():
    """Data display page"""
    return render_template('data.html')

@app.route('/api/jobs', methods=['POST'])
def create_job():
    """Create a new scraping job or resume existing incomplete job"""
    data = request.json
    app_url = data.get('app_url')
    max_reviews = data.get('max_reviews', 0)  # 0 means no limit
    max_pages = data.get('max_pages', 0)  # 0 means no limit
    
    if not app_url:
        return jsonify({'error': 'app_url is required'}), 400
    
    # Validate limits
    if max_reviews < 0:
        return jsonify({'error': 'max_reviews must be >= 0'}), 400
    if max_pages < 0:
        return jsonify({'error': 'max_pages must be >= 0'}), 400
    
    app_name = review_scraper.extract_app_name(app_url)
    
    # Check if job already exists
    existing_job = db.get_job_by_url(app_url)
    
    if existing_job:
        job_id = existing_job['id']
        is_complete = db.is_job_complete(job_id)
        
        if is_complete:
            return jsonify({
                'error': 'This review URL has already been completely scraped.',
                'job_id': job_id,
                'message': f'Job completed. Total reviews: {existing_job.get("reviews_scraped", 0)}'
            }), 400
        
        # Resume existing incomplete job
        logger.info(f"Resuming existing job {job_id} for {app_url}")
        current_page = existing_job.get('current_page', 0) or 0
        start_page = max(1, current_page + 1)  # Start from next page
        existing_reviews_count = existing_job.get('reviews_scraped', 0) or 0
        
        # Get limits from existing job or use new ones
        existing_max_reviews = existing_job.get('max_reviews_limit', 0) or 0
        existing_max_pages = existing_job.get('max_pages_limit', 0) or 0
        
        # If new limits are provided, update them; otherwise use existing
        # Use new limits if provided, otherwise keep existing limits
        final_max_reviews_limit = max_reviews if max_reviews > 0 else existing_max_reviews
        final_max_pages_limit = max_pages if max_pages > 0 else existing_max_pages
        
        # If limits were updated, store the new values
        if (max_reviews > 0 and max_reviews != existing_max_reviews) or (max_pages > 0 and max_pages != existing_max_pages):
            db.update_job_status(job_id, existing_job.get('status', 'scraping_reviews'),
                                max_reviews_limit=final_max_reviews_limit,
                                max_pages_limit=final_max_pages_limit)
        
        # Calculate remaining limits for this batch
        remaining_reviews = final_max_reviews_limit - existing_reviews_count if final_max_reviews_limit > 0 else 0
        remaining_pages = final_max_pages_limit - current_page if final_max_pages_limit > 0 else 0
        
        def resume_scraping():
            try:
                # Track final page count
                final_page_tracked = [current_page]  # Start from last known page
                
                def progress_callback(message, current_page_val, total_pages, reviews_count):
                    final_page_tracked[0] = current_page_val  # Update tracked page
                    db.update_job_status(
                        job_id, 
                        'scraping_reviews',
                        progress_message=message,
                        current_page=current_page_val,
                        total_pages=total_pages,
                        reviews_scraped=existing_reviews_count + reviews_count,  # Total reviews including existing
                        max_reviews_limit=final_max_reviews_limit,
                        max_pages_limit=final_max_pages_limit
                    )
                
                # Resume from where we left off with remaining limits
                # Scrape only remaining reviews/pages up to the limits
                reviews = review_scraper.scrape_all_pages(
                    app_url, 
                    max_pages=remaining_pages if final_max_pages_limit > 0 else 0, 
                    start_page=start_page,
                    max_reviews=remaining_reviews if final_max_reviews_limit > 0 else 0,
                    progress_callback=progress_callback
                )
                
                # Calculate final counts
                total_reviews = existing_reviews_count + len(reviews)
                # Use tracked page from callback, or estimate if not available
                final_current_page = final_page_tracked[0] if final_page_tracked[0] > current_page else (current_page + (len(reviews) // 10 + 1) if reviews else current_page)
                
                # Check if limits were reached or if scraping is truly complete
                reached_reviews_limit = final_max_reviews_limit > 0 and total_reviews >= final_max_reviews_limit
                reached_pages_limit = final_max_pages_limit > 0 and final_current_page >= final_max_pages_limit
                no_more_reviews = len(reviews) == 0
                
                # Only add new reviews if we got any
                if reviews:
                    db.add_stores(reviews, job_id, app_name)
                
                # Determine if we should continue or move to next phase
                if no_more_reviews:
                    # No more reviews found, mark as complete
                    db.update_job_status(
                        job_id,
                        'finding_urls',
                        total_stores=total_reviews,
                        reviews_scraped=total_reviews,
                        current_page=final_current_page,
                        progress_message=f"Finished scraping. Total reviews: {total_reviews}. Ready for URL finding."
                    )
                elif reached_reviews_limit or reached_pages_limit:
                    # Limits reached, but more reviews might exist - keep status as scraping_reviews
                    limit_msg = []
                    if reached_reviews_limit:
                        limit_msg.append(f"reached max reviews limit ({final_max_reviews_limit})")
                    if reached_pages_limit:
                        limit_msg.append(f"reached max pages limit ({final_max_pages_limit})")
                    
                    db.update_job_status(
                        job_id,
                        'scraping_reviews',
                        total_stores=total_reviews,
                        reviews_scraped=total_reviews,
                        current_page=final_current_page,
                        progress_message=f"Batch complete. Scraped {total_reviews} total reviews ({len(reviews)} new). {', '.join(limit_msg)}. Paste URL again to continue."
                    )
                else:
                    # Unexpected case - reviews found but no limits reached, continue
                    db.update_job_status(
                        job_id,
                        'finding_urls',
                        total_stores=total_reviews,
                        reviews_scraped=total_reviews,
                        current_page=final_current_page,
                        progress_message=f"Scraped {total_reviews} total reviews ({len(reviews)} new). Ready for URL finding."
                    )
            except Exception as e:
                logger.error(f"Error resuming review scraping: {e}", exc_info=True)
                db.update_job_status(job_id, 'error', progress_message=f"Error: {str(e)}")
        
        thread = threading.Thread(target=resume_scraping)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'job_id': job_id, 
            'app_name': app_name,
            'resumed': True,
            'message': f'Resuming from page {start_page}. Previously scraped {current_page} pages, {existing_reviews_count} reviews.',
            'remaining_pages': remaining_pages if final_max_pages_limit > 0 else 'unlimited',
            'remaining_reviews': remaining_reviews if final_max_reviews_limit > 0 else 'unlimited'
        })
    
    # Create new job
    job_id = db.create_job(app_name, app_url, max_reviews_limit=max_reviews, max_pages_limit=max_pages)
    logger.info(f"Created new job {job_id} for {app_url} with limits: max_reviews={max_reviews}, max_pages={max_pages}")
    
    def scrape_reviews():
        try:
            def progress_callback(message, current_page, total_pages, reviews_count):
                db.update_job_status(
                    job_id, 
                    'scraping_reviews',
                    progress_message=message,
                    current_page=current_page,
                    total_pages=total_pages,
                    reviews_scraped=reviews_count,
                    max_reviews_limit=max_reviews,
                    max_pages_limit=max_pages
                )
            
            # Track final page count during scraping
            final_page_count = [0]  # Use list to allow modification in nested function
            
            def tracked_progress_callback(message, current_page_val, total_pages, reviews_count):
                final_page_count[0] = current_page_val  # Track latest page
                progress_callback(message, current_page_val, total_pages, reviews_count)
            
            reviews = review_scraper.scrape_all_pages(
                app_url, 
                max_pages=max_pages, 
                start_page=1,
                max_reviews=max_reviews,
                progress_callback=tracked_progress_callback
            )
            
            if reviews:
                db.add_stores(reviews, job_id, app_name)
            
            # Check if limits were reached
            total_reviews_scraped = len(reviews)
            final_page = final_page_count[0] if final_page_count[0] > 0 else (max_pages if max_pages > 0 else (len(reviews) // 10 + 1))
            
            reached_reviews_limit = max_reviews > 0 and total_reviews_scraped >= max_reviews
            reached_pages_limit = max_pages > 0 and final_page >= max_pages
            no_more_reviews = total_reviews_scraped == 0  # Could mean no more reviews exist
            
            if no_more_reviews:
                # No reviews found, might be complete
                db.update_job_status(
                    job_id, 
                    'finding_urls', 
                    total_stores=total_reviews_scraped,
                    reviews_scraped=total_reviews_scraped,
                    current_page=final_page,
                    progress_message=f"Finished scraping. Found {total_reviews_scraped} reviews. Ready for URL finding."
                )
            elif reached_reviews_limit or reached_pages_limit:
                # Limits reached, keep as scraping_reviews so it can be resumed
                limit_msg = []
                if reached_reviews_limit:
                    limit_msg.append(f"reached max reviews limit ({max_reviews})")
                if reached_pages_limit:
                    limit_msg.append(f"reached max pages limit ({max_pages})")
                
                db.update_job_status(
                    job_id,
                    'scraping_reviews',
                    total_stores=total_reviews_scraped,
                    reviews_scraped=total_reviews_scraped,
                    current_page=final_page,
                    max_reviews_limit=max_reviews,
                    max_pages_limit=max_pages,
                    progress_message=f"Batch complete. Scraped {total_reviews_scraped} reviews. {', '.join(limit_msg)}. Paste URL again to continue."
                )
            else:
                # No limits or scraping naturally completed, move to next phase
                db.update_job_status(
                    job_id, 
                    'finding_urls', 
                    total_stores=total_reviews_scraped,
                    reviews_scraped=total_reviews_scraped,
                    current_page=final_page,
                    progress_message=f"Scraped {total_reviews_scraped} reviews. Ready for URL finding."
                )
        except Exception as e:
            logger.error(f"Error scraping reviews: {e}", exc_info=True)
            db.update_job_status(job_id, 'error', progress_message=f"Error: {str(e)}")
    
    thread = threading.Thread(target=scrape_reviews)
    thread.daemon = True
    thread.start()
    
    return jsonify({'job_id': job_id, 'app_name': app_name, 'resumed': False})

@app.route('/api/jobs')
def get_all_jobs():
    """Get all jobs"""
    jobs = db.get_all_jobs()
    return jsonify(jobs)

@app.route('/api/jobs/<int:job_id>')
def get_job(job_id):
    """Get job status"""
    job = db.get_job(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    stats = db.get_statistics(job_id)
    job['statistics'] = stats
    
    return jsonify(job)

@app.route('/api/stores/pending')
def get_pending_stores():
    """Get stores pending URL verification"""
    limit = request.args.get('limit', type=int)
    stores = db.get_pending_stores(limit=limit)
    return jsonify(stores)

@app.route('/api/stores/next')
def get_next_store():
    """Get the next pending store (one at a time)"""
    store = db.get_next_pending_store()
    if not store:
        return jsonify({'store': None, 'message': 'No more stores pending'})
    return jsonify({'store': store})

@app.route('/api/stores/<int:store_id>/skip', methods=['POST'])
def skip_store(store_id):
    """Skip a store"""
    db.skip_store(store_id)
    return jsonify({'success': True})

@app.route('/api/stores/<int:store_id>')
def get_store(store_id):
    """Get a single store"""
    store = db.get_store(store_id)
    if not store:
        return jsonify({'error': 'Store not found'}), 404
    return jsonify(store)

@app.route('/api/stores/<int:store_id>/url', methods=['PUT'])
def update_store_url(store_id):
    """Update store URL and start email scraping"""
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({'error': 'url is required'}), 400
    
    # Clean the URL before saving (clean_url is synchronous)
    cleaned_url = url_finder.clean_url(url)
    db.update_store_url(store_id, cleaned_url)
    
    # Get store name for context in email processing
    store = db.get_store(store_id)
    store_name = store.get('store_name') if store else None
    
    # Start email scraping in background
    def scrape_emails():
        emails = []
        raw_emails = []
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # Step 1: Scrape raw emails
                result = loop.run_until_complete(email_scraper.scrape_emails(cleaned_url, store_name))
                
                # Extract raw emails
                if isinstance(result, dict):
                    raw_emails = result.get('raw_emails', [])
                else:
                    raw_emails = result if isinstance(result, list) else []
                
                logger.info(f"Email scraping completed for store {store_id}.")
                logger.info(f"  - Raw emails found: {len(raw_emails)}")
                
                # Step 2: Use AI to extract only relevant emails
                if ai_email_extractor and raw_emails:
                    logger.info(f"Using AI to extract relevant emails from {len(raw_emails)} raw emails...")
                    # AI extraction is synchronous, call directly
                    ai_result = ai_email_extractor.extract_relevant_emails(
                        raw_emails,
                        cleaned_url,
                        store_name
                    )
                    emails = ai_result.get('emails', [])
                    ai_stats = ai_result.get('stats', {})
                    
                    logger.info(f"AI extraction completed:")
                    logger.info(f"  - Raw emails: {ai_stats.get('total_raw', 0)}")
                    logger.info(f"  - Relevant emails: {ai_stats.get('total_relevant', 0)}")
                else:
                    if not ai_email_extractor:
                        logger.warning("AI Email Extractor not available, storing all raw emails")
                    emails = raw_emails
                
            except Exception as e:
                logger.error(f"Error during email scraping: {e}", exc_info=True)
                # Continue to update status even on error
            finally:
                if loop:
                    loop.close()
            
            # ALWAYS update store status, even if no emails found or error occurred
            # This ensures the frontend knows scraping is complete
            try:
                db.update_store_emails(store_id, emails, raw_emails)
                logger.info(f"Stored {len(emails)} relevant emails and {len(raw_emails)} raw emails for store {store_id}.")
            except Exception as e:
                logger.error(f"Error updating store emails in database: {e}", exc_info=True)
                
        except Exception as e:
            logger.error(f"Critical error in email scraping thread: {e}", exc_info=True)
            # Last resort: try to mark as complete with empty emails
            try:
                db.update_store_emails(store_id, [], [])
                logger.info(f"Marked store {store_id} as complete (no emails) after error")
            except:
                logger.error(f"Failed to update store status after critical error")
    
    thread = threading.Thread(target=scrape_emails)
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'url': cleaned_url, 'message': 'URL saved. Email scraping started in background.'})

@app.route('/api/stores/<int:store_id>/emails', methods=['PUT'])
def update_store_emails_manual(store_id):
    """Manually update cleaned emails for a store"""
    data = request.json
    emails = data.get('emails', [])
    
    if not isinstance(emails, list):
        return jsonify({'error': 'emails must be a list'}), 400
    
    # Validate email format
    import re
    email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')
    valid_emails = []
    for email in emails:
        email = email.strip()
        if email and email_pattern.match(email):
            valid_emails.append(email)
    
    # Get current store to preserve raw_emails
    store = db.get_store(store_id)
    if not store:
        return jsonify({'error': 'Store not found'}), 404
    
    raw_emails = store.get('raw_emails', [])
    
    # Update only cleaned emails, preserve raw_emails
    db.update_store_emails(store_id, valid_emails, raw_emails)
    logger.info(f"Manually updated {len(valid_emails)} emails for store {store_id}")
    
    return jsonify({
        'success': True,
        'emails': valid_emails,
        'message': f'Updated {len(valid_emails)} emails'
    })

@app.route('/api/stores')
def get_all_stores():
    """Get all stores"""
    app_name = request.args.get('app_name')
    stores = db.get_all_stores(app_name=app_name)
    return jsonify(stores)

@app.route('/api/stores/export', methods=['POST'])
def export_stores():
    """Export filtered stores to CSV"""
    import csv
    import io
    
    data = request.json
    store_ids = data.get('store_ids', [])
    
    if not store_ids:
        return jsonify({'error': 'No stores to export'}), 400
    
    # Get stores by IDs
    all_stores = db.get_all_stores()
    stores_to_export = [s for s in all_stores if s['id'] in store_ids]
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        'ID', 'Store Name', 'Country', 'Rating', 'Review Text', 'Review Date',
        'Usage Duration', 'Base URL', 'Raw Emails', 'Cleaned Emails',
        'Status', 'App Name', 'Created At'
    ])
    
    # Write data
    for store in stores_to_export:
        raw_emails = store.get('raw_emails', [])
        cleaned_emails = store.get('emails', [])
        writer.writerow([
            store.get('id'),
            store.get('store_name', ''),
            store.get('country', ''),
            store.get('rating', ''),
            store.get('review_text', ''),
            store.get('review_date', ''),
            store.get('usage_duration', ''),
            store.get('base_url', ''),
            ', '.join(raw_emails) if raw_emails else '',
            ', '.join(cleaned_emails) if cleaned_emails else '',
            store.get('status', ''),
            store.get('app_name', ''),
            store.get('created_at', '')
        ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=shopify_stores_export.csv'}
    )

@app.route('/api/stores/delete', methods=['POST'])
def delete_stores():
    """Delete stores and associated jobs"""
    data = request.json
    store_ids = data.get('store_ids', [])
    
    if not store_ids:
        return jsonify({'error': 'No stores to delete'}), 400
    
    if not isinstance(store_ids, list):
        return jsonify({'error': 'store_ids must be a list'}), 400
    
    try:
        result = db.delete_stores(store_ids)
        return jsonify({
            'success': True,
            'stores_deleted': result['stores_deleted'],
            'jobs_deleted': result['jobs_deleted'],
            'app_urls': result['app_urls'],
            'message': f"Deleted {result['stores_deleted']} stores and {result['jobs_deleted']} review page URLs"
        })
    except Exception as e:
        logger.error(f"Error deleting stores: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500



@app.route('/api/search/results', methods=['POST'])
def receive_search_results():
    """Receive search results from Chrome extension"""
    data = request.json
    query = data.get('query')
    urls = data.get('urls', [])
    
    logger.info(f"Received {len(urls)} URLs from extension for query: {query}")
    
    return jsonify({
        'success': True,
        'urls': urls,
        'count': len(urls)
    })


# Store pending search requests
pending_searches = {}
search_results = {}


@app.route('/api/search/request', methods=['POST'])
def request_search():
    """Request a search from extension - returns search_id for polling"""
    data = request.json
    store_name = data.get('store_name')
    
    if not store_name:
        return jsonify({'error': 'store_name is required'}), 400
    
    # Clean store name
    import re
    clean_name = store_name
    clean_name = re.sub(r'\s*shopify\s*store\s*', ' ', clean_name, flags=re.IGNORECASE)
    clean_name = re.sub(r'\s*\|\s*[A-Z]{2}\s*', ' ', clean_name)
    clean_name = re.sub(r'\s*(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}', '', clean_name, flags=re.IGNORECASE)
    clean_name = re.sub(r'\s+\d{1,2}/\d{1,2}/\d{4}', '', clean_name)
    clean_name = ' '.join(clean_name.split()).strip()
    
    import uuid
    search_id = str(uuid.uuid4())
    pending_searches[search_id] = {
        'query': clean_name,
        'created_at': time.time(),
        'status': 'pending'
    }
    
    logger.info(f"Search requested: query='{clean_name}', search_id={search_id}")
    
    return jsonify({
        'success': True,
        'search_id': search_id,
        'query': clean_name,
        'message': 'Search requested. Extension will process it.'
    })


@app.route('/api/search/poll/<search_id>', methods=['GET'])
def poll_search_results(search_id):
    """Poll for search results"""
    if search_id in search_results:
        results = search_results.pop(search_id)
        if search_id in pending_searches:
            del pending_searches[search_id]
        return jsonify({
            'success': True,
            'urls': results.get('urls', []),
            'status': 'complete'
        })
    elif search_id in pending_searches:
        return jsonify({
            'success': True,
            'urls': [],
            'status': 'pending'
        })
    else:
        return jsonify({
            'error': 'Search ID not found'
        }), 404


@app.route('/api/search/extension/submit', methods=['POST', 'OPTIONS'])
def extension_submit_results():
    """Extension submits results here"""
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response
    
    data = request.json
    query = data.get('query')
    urls = data.get('urls', [])
    search_id = data.get('search_id')
    
    logger.info(f"Extension submitting results: query='{query}', search_id={search_id}, url_count={len(urls)}")
    
    # Find matching pending search by query if search_id not provided
    if not search_id:
        for sid, search in list(pending_searches.items()):
            if search['query'].lower() == query.lower():
                search_id = sid
                logger.info(f"Matched search by query, found search_id: {search_id}")
                break
    
    if search_id:
        search_results[search_id] = {
            'urls': urls,
            'query': query,
            'received_at': time.time()
        }
        # Remove from pending
        if search_id in pending_searches:
            del pending_searches[search_id]
        logger.info(f"Extension submitted {len(urls)} URLs for search_id: {search_id}, query: {query}")
    else:
        # Create a new search_id if not found (shouldn't happen, but handle it)
        import uuid
        search_id = str(uuid.uuid4())
        search_results[search_id] = {
            'urls': urls,
            'query': query,
            'received_at': time.time()
        }
        logger.warning(f"Extension submitted {len(urls)} URLs without matching search_id, created new: {search_id}, query: {query}")
    
    response = jsonify({'success': True, 'search_id': search_id})
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response


@app.route('/api/ai/select-url', methods=['POST', 'OPTIONS'])
def ai_select_url():
    """Use AI to select the best URL from search results"""
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response
    
    if not ai_selector:
        return jsonify({
            'error': 'AI URL Selector is not available. Check API key configuration.'
        }), 503
    
    data = request.json
    store_name = data.get('store_name')
    country = data.get('country')
    review_text = data.get('review_text')
    search_results = data.get('search_results', [])
    
    if not store_name:
        return jsonify({'error': 'store_name is required'}), 400
    
    if not search_results or len(search_results) == 0:
        return jsonify({'error': 'search_results is required and cannot be empty'}), 400
    
    try:
        logger.info(f"AI selecting URL for store: {store_name}")
        result = ai_selector.select_best_url(
            store_name=store_name,
            country=country,
            review_text=review_text,
            search_results=search_results
        )
        
        logger.info(f"AI selected URL: {result['selected_url']} (confidence: {result['confidence']:.2f})")
        
        return jsonify({
            'success': True,
            'selected_url': result['selected_url'],
            'confidence': result['confidence'],
            'reasoning': result['reasoning'],
            'selected_index': result['selected_index']
        })
    except Exception as e:
        logger.error(f"Error in AI URL selection: {e}", exc_info=True)
        return jsonify({
            'error': f'AI selection failed: {str(e)}'
        }), 500


@app.route('/api/search/extension/pending', methods=['GET', 'OPTIONS'])
def get_pending_search():
    """Extension polls this to get pending searches"""
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response
    
    # Return oldest pending search that hasn't been processed
    active_searches = {k: v for k, v in pending_searches.items() 
                       if v.get('status') == 'pending'}
    
    logger.info(f"Extension polling for pending searches. Active: {len(active_searches)}, Total pending: {len(pending_searches)}")
    
    if active_searches:
        oldest_id = min(active_searches.keys(), 
                       key=lambda k: active_searches[k]['created_at'])
        search = active_searches[oldest_id]
        # Mark as processing
        pending_searches[oldest_id]['status'] = 'processing'
        logger.info(f"Extension requested search: {search['query']} (search_id: {oldest_id})")
        response = jsonify({
            'query': search['query'],
            'search_id': oldest_id
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
    
    # Log when no searches found (but not too often)
    import random
    if random.random() < 0.1:  # Log 10% of empty polls
        logger.debug("Extension polled but no pending searches")
    
    response = jsonify({'query': None, 'search_id': None})
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response


@app.route('/api/search/extension/status', methods=['GET', 'OPTIONS'])
def extension_status():
    """Check if extension is active (if it's polling this endpoint)"""
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response
    
    # This is just to verify extension can reach Flask
    response = jsonify({
        'status': 'active',
        'message': 'Extension can reach Flask server'
    })
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response


@app.route('/api/statistics')
def get_statistics():
    """Get overall statistics"""
    job_id = request.args.get('job_id', type=int)
    stats = db.get_statistics(job_id=job_id)
    return jsonify(stats)

if __name__ == '__main__':
    logger.info(f"Starting server on {HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=DEBUG)

