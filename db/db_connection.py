"""
Database connection management
"""
import logging
import psycopg2
from contextlib import contextmanager

from config.settings import DB_CONFIG

logger = logging.getLogger(__name__)

class DatabaseConnection:
    """Singleton database connection manager"""
    _instance = None
    _connection = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseConnection, cls).__new__(cls)
        return cls._instance
    
    def get_connection(self):
        """Get or create database connection"""
        if self._connection is None or self._connection.closed:
            try:
                self._connection = psycopg2.connect(**DB_CONFIG)
                logger.info("Database connection established")
            except Exception as e:
                logger.error(f"Failed to connect to database: {e}")
                raise
        return self._connection
    
    def close(self):
        """Close database connection"""
        if self._connection and not self._connection.closed:
            self._connection.close()
            self._connection = None
            logger.info("Database connection closed")

@contextmanager
def get_db_cursor():
    """
    Context manager for database operations
    Usage:
        with get_db_cursor() as cur:
            cur.execute("SELECT * FROM table")
    """
    conn = None
    cur = None
    try:
        db = DatabaseConnection()
        conn = db.get_connection()
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        if cur:
            cur.close()
        # Note: Connection is managed by singleton, not closed here