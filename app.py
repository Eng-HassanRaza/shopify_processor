"""Main Flask application"""
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import logging
import threading
import asyncio
from config import HOST, PORT, DEBUG, DATABASE_PATH
from database import Database
from modules.review_scraper import ReviewScraper
from modules.url_finder import URLFinder
from modules.email_scraper import EmailScraper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

db = Database(str(DATABASE_PATH))
review_scraper = ReviewScraper()
url_finder = URLFinder(headless=False)  # Visible browser for manual search
email_scraper = EmailScraper()

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

@app.route('/api/search', methods=['POST'])
def search_google():
    """Open Google search in browser for manual search"""
    data = request.json
    store_name = data.get('store_name')
    country = data.get('country', '')
    
    if not store_name:
        return jsonify({'error': 'store_name is required'}), 400
    
    def open_search():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(url_finder.open_google_search(store_name, country))
            return {'success': True, 'message': 'Browser opened with Google search. Please find and copy the store URL.'}
        except Exception as e:
            logger.error(f"Error opening browser: {e}")
            return {'error': str(e)}
        finally:
            loop.close()
    
    result = open_search()
    return jsonify(result)


@app.route('/api/statistics')
def get_statistics():
    """Get overall statistics"""
    job_id = request.args.get('job_id', type=int)
    stats = db.get_statistics(job_id=job_id)
    return jsonify(stats)

if __name__ == '__main__':
    logger.info(f"Starting server on {HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=DEBUG)

