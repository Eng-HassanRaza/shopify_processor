"""Database management for Shopify Review Processor"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        """Get database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        """Initialize database schema"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Stores table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_name TEXT NOT NULL,
                country TEXT,
                review_date TEXT,
                review_text TEXT,
                usage_duration TEXT,
                base_url TEXT,
                url_verified BOOLEAN DEFAULT 0,
                verified_at TEXT,
                emails TEXT,  -- JSON array of emails
                emails_found INTEGER DEFAULT 0,
                emails_scraped_at TEXT,
                status TEXT DEFAULT 'pending_url',  -- pending_url, url_found, url_verified, emails_found, completed
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                app_name TEXT
            )
        """)
        
        # Jobs table (for tracking scraping jobs)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_name TEXT NOT NULL,
                app_url TEXT NOT NULL,
                total_stores INTEGER DEFAULT 0,
                stores_processed INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',  -- pending, scraping_reviews, finding_urls, scraping_emails, completed
                progress_message TEXT,
                current_page INTEGER DEFAULT 0,
                total_pages INTEGER DEFAULT 0,
                reviews_scraped INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        
        # Migrate existing jobs table if needed
        try:
            cursor.execute("SELECT progress_message FROM jobs LIMIT 1")
        except sqlite3.OperationalError:
            logger.info("Migrating jobs table...")
            cursor.execute("ALTER TABLE jobs ADD COLUMN progress_message TEXT")
            cursor.execute("ALTER TABLE jobs ADD COLUMN current_page INTEGER DEFAULT 0")
            cursor.execute("ALTER TABLE jobs ADD COLUMN total_pages INTEGER DEFAULT 0")
            cursor.execute("ALTER TABLE jobs ADD COLUMN reviews_scraped INTEGER DEFAULT 0")
            conn.commit()
            logger.info("Migration complete")
        
        conn.close()
        logger.info("Database initialized")
    
    def job_exists(self, app_url: str) -> bool:
        """Check if a job with this app_url already exists"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM jobs WHERE app_url = ?", (app_url,))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists
    
    def create_job(self, app_name: str, app_url: str) -> int:
        """Create a new scraping job"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO jobs (app_name, app_url, status)
            VALUES (?, ?, 'scraping_reviews')
        """, (app_name, app_url))
        
        job_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return job_id
    
    def update_job_status(self, job_id: int, status: str, total_stores: int = None, stores_processed: int = None, 
                         progress_message: str = None, current_page: int = None, total_pages: int = None,
                         reviews_scraped: int = None):
        """Update job status"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        updates = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        params = [status]
        
        if total_stores is not None:
            updates.append("total_stores = ?")
            params.append(total_stores)
        
        if stores_processed is not None:
            updates.append("stores_processed = ?")
            params.append(stores_processed)
        
        if progress_message is not None:
            updates.append("progress_message = ?")
            params.append(progress_message)
        
        if current_page is not None:
            updates.append("current_page = ?")
            params.append(current_page)
        
        if total_pages is not None:
            updates.append("total_pages = ?")
            params.append(total_pages)
        
        if reviews_scraped is not None:
            updates.append("reviews_scraped = ?")
            params.append(reviews_scraped)
        
        params.append(job_id)
        
        cursor.execute(f"""
            UPDATE jobs SET {', '.join(updates)}
            WHERE id = ?
        """, params)
        
        conn.commit()
        conn.close()
    
    def add_stores(self, stores: List[Dict], job_id: int, app_name: str):
        """Add stores from review scraping"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        for store in stores:
            cursor.execute("""
                INSERT INTO stores (
                    store_name, country, review_date, review_text, usage_duration,
                    app_name, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending_url')
            """, (
                store.get('store_name'),
                store.get('country'),
                store.get('review_date'),
                store.get('review_text'),
                store.get('usage_duration'),
                app_name
            ))
        
        conn.commit()
        conn.close()
        logger.info(f"Added {len(stores)} stores to database")
    
    def get_pending_stores(self, limit: int = None) -> List[Dict]:
        """Get stores that need URL finding"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = """
            SELECT * FROM stores
            WHERE status = 'pending_url' OR status = 'url_found'
            ORDER BY id
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        
        stores = []
        for row in rows:
            store = dict(row)
            # Parse emails JSON
            if store.get('emails'):
                try:
                    store['emails'] = json.loads(store['emails'])
                except:
                    store['emails'] = []
            else:
                store['emails'] = []
            stores.append(store)
        
        return stores
    
    def get_next_pending_store(self) -> Optional[Dict]:
        """Get the next pending store (one at a time)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM stores
            WHERE status = 'pending_url'
            ORDER BY id
            LIMIT 1
        """)
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            store = dict(row)
            # Parse emails JSON
            if store.get('emails'):
                try:
                    store['emails'] = json.loads(store['emails'])
                except:
                    store['emails'] = []
            else:
                store['emails'] = []
            return store
        return None
    
    def skip_store(self, store_id: int):
        """Skip a store (mark as skipped)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE stores
            SET status = 'skipped', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (store_id,))
        
        conn.commit()
        conn.close()
    
    def update_store_url(self, store_id: int, url: str):
        """Update store with verified URL"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE stores
            SET base_url = ?, url_verified = 1, verified_at = CURRENT_TIMESTAMP,
                status = 'url_verified', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (url, store_id))
        
        conn.commit()
        conn.close()
    
    def update_store_emails(self, store_id: int, emails: List[str]):
        """Update store with scraped emails"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        emails_json = json.dumps(emails)
        
        cursor.execute("""
            UPDATE stores
            SET emails = ?, emails_found = ?, emails_scraped_at = CURRENT_TIMESTAMP,
                status = 'emails_found', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (emails_json, len(emails), store_id))
        
        conn.commit()
        conn.close()
    
    def get_store(self, store_id: int) -> Optional[Dict]:
        """Get a single store by ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM stores WHERE id = ?", (store_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            store = dict(row)
            # Parse emails JSON
            if store.get('emails'):
                try:
                    store['emails'] = json.loads(store['emails'])
                except:
                    store['emails'] = []
            else:
                store['emails'] = []
            return store
        return None
    
    def get_all_stores(self, app_name: str = None) -> List[Dict]:
        """Get all stores, optionally filtered by app name"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if app_name:
            cursor.execute("SELECT * FROM stores WHERE app_name = ? ORDER BY id", (app_name,))
        else:
            cursor.execute("SELECT * FROM stores ORDER BY id")
        
        rows = cursor.fetchall()
        conn.close()
        
        stores = []
        for row in rows:
            store = dict(row)
            # Parse emails JSON
            if store.get('emails'):
                try:
                    store['emails'] = json.loads(store['emails'])
                except:
                    store['emails'] = []
            else:
                store['emails'] = []
            stores.append(store)
        
        return stores
    
    def get_job(self, job_id: int) -> Optional[Dict]:
        """Get job by ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    def get_all_jobs(self) -> List[Dict]:
        """Get all jobs ordered by creation date"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_statistics(self, job_id: int = None) -> Dict:
        """Get processing statistics"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if job_id:
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'pending_url' THEN 1 ELSE 0 END) as pending_url,
                    SUM(CASE WHEN status = 'url_verified' THEN 1 ELSE 0 END) as url_verified,
                    SUM(CASE WHEN status = 'emails_found' THEN 1 ELSE 0 END) as emails_found,
                    SUM(emails_found) as total_emails
                FROM stores
                WHERE app_name = (SELECT app_name FROM jobs WHERE id = ?)
            """, (job_id,))
        else:
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'pending_url' THEN 1 ELSE 0 END) as pending_url,
                    SUM(CASE WHEN status = 'url_verified' THEN 1 ELSE 0 END) as url_verified,
                    SUM(CASE WHEN status = 'emails_found' THEN 1 ELSE 0 END) as emails_found,
                    SUM(emails_found) as total_emails
                FROM stores
            """)
        
        row = cursor.fetchone()
        conn.close()
        
        stats = dict(row) if row else {}
        # Ensure total_emails is not None
        if stats.get('total_emails') is None:
            stats['total_emails'] = 0
        return stats

