"""Main Flask application"""
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import logging
import threading
import asyncio
import requests
import time
from config import HOST, PORT, DEBUG, DATABASE_PATH
from database import Database
from modules.review_scraper import ReviewScraper
from modules.url_finder import URLFinder
from modules.email_scraper import EmailScraper

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
email_scraper = EmailScraper()

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

@app.route('/api/jobs', methods=['POST'])
def create_job():
    """Create a new scraping job"""
    data = request.json
    app_url = data.get('app_url')
    
    if not app_url:
        return jsonify({'error': 'app_url is required'}), 400
    
    # Check if this URL was already scraped
    if db.job_exists(app_url):
        return jsonify({'error': 'This app URL has already been scraped. Each review URL (1-star, 2-star, etc.) should be unique.'}), 400
    
    app_name = review_scraper.extract_app_name(app_url)
    job_id = db.create_job(app_name, app_url)
    
    def scrape_reviews():
        try:
            def progress_callback(message, current_page, total_pages, reviews_count):
                db.update_job_status(
                    job_id, 
                    'scraping_reviews',
                    progress_message=message,
                    current_page=current_page,
                    total_pages=total_pages,
                    reviews_scraped=reviews_count
                )
            
            reviews = review_scraper.scrape_all_pages(app_url, max_pages=0, progress_callback=progress_callback)
            db.add_stores(reviews, job_id, app_name)
            db.update_job_status(
                job_id, 
                'finding_urls', 
                total_stores=len(reviews),
                progress_message=f"Scraped {len(reviews)} reviews. Ready for URL finding."
            )
        except Exception as e:
            logger.error(f"Error scraping reviews: {e}", exc_info=True)
            db.update_job_status(job_id, 'error', progress_message=f"Error: {str(e)}")
    
    thread = threading.Thread(target=scrape_reviews)
    thread.daemon = True
    thread.start()
    
    return jsonify({'job_id': job_id, 'app_name': app_name})

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
    
    # Start email scraping in background
    def scrape_emails():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                emails = loop.run_until_complete(email_scraper.scrape_emails(cleaned_url))
                db.update_store_emails(store_id, emails)
                logger.info(f"Email scraping completed for store {store_id}. Found {len(emails)} emails.")
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"Error scraping emails: {e}")
    
    thread = threading.Thread(target=scrape_emails)
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'url': cleaned_url, 'message': 'URL saved. Email scraping started in background.'})

@app.route('/api/stores')
def get_all_stores():
    """Get all stores"""
    app_name = request.args.get('app_name')
    stores = db.get_all_stores(app_name=app_name)
    return jsonify(stores)



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

