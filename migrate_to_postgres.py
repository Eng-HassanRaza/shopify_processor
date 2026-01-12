#!/usr/bin/env python3
"""Migration script to transfer data from SQLite to PostgreSQL"""
import sqlite3
import psycopg2
import psycopg2.extras
import json
import sys
from pathlib import Path
from config import DATABASE_URL, DATABASE_PATH

def migrate_sqlite_to_postgres():
    """Migrate data from SQLite database to PostgreSQL"""
    
    # Check if SQLite database exists
    sqlite_path = Path(DATABASE_PATH)
    if not sqlite_path.exists():
        print(f"SQLite database not found at {sqlite_path}")
        print("No migration needed - using fresh PostgreSQL database")
        return
    
    print(f"Migrating data from SQLite: {sqlite_path}")
    print(f"To PostgreSQL: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL}")
    
    # Connect to SQLite
    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()
    
    # Connect to PostgreSQL and initialize schema first
    print("Initializing PostgreSQL schema...")
    sys.path.insert(0, str(Path(__file__).parent))
    from database import Database
    pg_db = Database(DATABASE_URL)
    print("  Schema initialized")
    
    # Connect to PostgreSQL for migration
    pg_conn = psycopg2.connect(DATABASE_URL)
    pg_cursor = pg_conn.cursor()
    
    try:
        # Check if PostgreSQL tables are empty
        pg_cursor.execute("SELECT COUNT(*) FROM stores")
        stores_count = pg_cursor.fetchone()[0]
        pg_cursor.execute("SELECT COUNT(*) FROM jobs")
        jobs_count = pg_cursor.fetchone()[0]
        
        if stores_count > 0 or jobs_count > 0:
            response = input(f"PostgreSQL database already has {stores_count} stores and {jobs_count} jobs. Continue migration? (yes/no): ")
            if response.lower() != 'yes':
                print("Migration cancelled")
                return
        
        # Migrate jobs table
        print("\nMigrating jobs table...")
        sqlite_cursor.execute("SELECT * FROM jobs")
        jobs = sqlite_cursor.fetchall()
        
        for job in jobs:
            job_dict = dict(job)
            pg_cursor.execute("""
                INSERT INTO jobs (
                    id, app_name, app_url, total_stores, stores_processed, status,
                    progress_message, current_page, total_pages, reviews_scraped,
                    max_reviews_limit, max_pages_limit, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (
                job_dict['id'], job_dict['app_name'], job_dict['app_url'], job_dict['total_stores'],
                job_dict['stores_processed'], job_dict['status'], job_dict.get('progress_message'),
                job_dict.get('current_page', 0), job_dict.get('total_pages', 0),
                job_dict.get('reviews_scraped', 0), job_dict.get('max_reviews_limit', 0),
                job_dict.get('max_pages_limit', 0), job_dict['created_at'], job_dict['updated_at']
            ))
        
        print(f"  Migrated {len(jobs)} jobs")
        
        # Migrate stores table
        print("\nMigrating stores table...")
        sqlite_cursor.execute("SELECT * FROM stores")
        stores = sqlite_cursor.fetchall()
        
        migrated_count = 0
        for store in stores:
            store_dict = dict(store)
            pg_cursor.execute("""
                INSERT INTO stores (
                    id, store_name, country, review_date, review_text, usage_duration,
                    rating, base_url, url_verified, verified_at, emails, raw_emails,
                    emails_found, emails_scraped_at, status, created_at, updated_at, app_name
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (
                store_dict['id'], store_dict['store_name'], store_dict['country'], store_dict['review_date'],
                store_dict['review_text'], store_dict['usage_duration'], store_dict.get('rating'),
                store_dict.get('base_url'), bool(store_dict.get('url_verified', 0)), store_dict.get('verified_at'),
                store_dict.get('emails'), store_dict.get('raw_emails'), store_dict.get('emails_found', 0),
                store_dict.get('emails_scraped_at'), store_dict['status'], store_dict['created_at'],
                store_dict['updated_at'], store_dict.get('app_name')
            ))
            migrated_count += 1
        
        print(f"  Migrated {migrated_count} stores")
        
        # Reset sequences to match the max ID
        print("\nResetting PostgreSQL sequences...")
        pg_cursor.execute("SELECT setval('stores_id_seq', (SELECT MAX(id) FROM stores))")
        pg_cursor.execute("SELECT setval('jobs_id_seq', (SELECT MAX(id) FROM jobs))")
        
        pg_conn.commit()
        print("\n✅ Migration completed successfully!")
        print(f"   Jobs: {len(jobs)}")
        print(f"   Stores: {migrated_count}")
        
    except Exception as e:
        pg_conn.rollback()
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        sqlite_conn.close()
        pg_conn.close()

if __name__ == "__main__":
    migrate_sqlite_to_postgres()
