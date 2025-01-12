import psycopg2
from psycopg2.extensions import connection
import configparser
import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.table import Table
from rich.logging import RichHandler
import sys
import signal
import psutil
import tracemalloc
import gc
import threading
from threading import Timer
import traceback
from contextlib import contextmanager
from typing import Dict, List, Tuple, Any, Optional
import time
from dataclasses import dataclass
from queue import Queue
import hashlib
from pathlib import Path
from functools import lru_cache

@dataclass
class TableInfo:
    """Data class for table migration information"""
    name: str
    source_rows: int = 0
    target_rows: int = 0
    source_size: str = '0 B'
    target_size: str = '0 B'
    success: bool = False
    error_message: str = ''
    checksum: str = ''

@dataclass
class DatabaseConfig:
    """Database configuration container with validation"""
    host: str
    port: int
    database: str
    user: str
    password: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for psycopg2"""
        return {
            'host': self.host,
            'port': self.port,
            'dbname': self.database,
            'user': self.user,
            'password': self.password
        }

    @classmethod
    def from_config(cls, config: configparser.ConfigParser) -> 'DatabaseConfig':
        """Create from ConfigParser object with validation"""
        try:
            postgresql = config['postgresql']
            return cls(
                host=postgresql['host'],
                port=int(postgresql['port']),
                database=postgresql['database'],
                user=postgresql['user'],
                password=postgresql['password']
            )
        except KeyError as e:
            raise ValueError(f"Missing required configuration key: {e}")
        except ValueError as e:
            raise ValueError(f"Invalid configuration value: {e}")

class SizeFormatter:
    """Utility class for formatting byte sizes"""
    UNITS = ['B', 'KB', 'MB', 'GB', 'TB']
    
    @staticmethod
    def format_size(size_bytes: int) -> str:
        """Format byte size to human readable string"""
        if size_bytes < 0:
            raise ValueError("Size cannot be negative")
            
        index = 0
        size = float(size_bytes)
        while size >= 1024 and index < len(SizeFormatter.UNITS) - 1:
            size /= 1024
            index += 1
        return f"{size:.2f} {SizeFormatter.UNITS[index]}"

def read_db_config(file_path: str) -> DatabaseConfig:
    """
    Read and validate database configuration from file
    
    Args:
        file_path: Path to configuration file
        
    Returns:
        DatabaseConfig object containing validated configuration
        
    Raises:
        FileNotFoundError: If configuration file doesn't exist
        ValueError: If configuration is invalid
        configparser.Error: If configuration file can't be parsed
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Reading database configuration from {file_path}")
    
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {file_path}")
        
    try:
        config = configparser.ConfigParser()
        config.read(file_path)
        
        # Validate required section exists
        if 'postgresql' not in config:
            raise ValueError("Missing 'postgresql' section in configuration")
            
        return DatabaseConfig.from_config(config)
        
    except (configparser.Error, ValueError) as e:
        logger.error(f"Failed to read database configuration: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error reading configuration: {str(e)}")
        raise

def ensure_table_exists(source_conn: connection, target_conn: connection, 
                       table_name: str) -> None:
    """
    Ensure table exists in target database with proper schema
    
    Args:
        source_conn: Source database connection
        target_conn: Target database connection
        table_name: Name of table to verify/create
        
    Raises:
        psycopg2.Error: On database errors
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Ensuring table exists in target database: {table_name}")
    
    try:
        # Verify table nameto prevent SQL injection
        if not table_name.isalnum() and not all(c in '_' for c in table_name):
            raise ValueError(f"Invalid table name: {table_name}")
            
        create_table_sql = get_table_schema(source_conn, table_name)
        
        with target_conn.cursor() as target_cur:
            target_cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = %s
                )
            """, (table_name,))
            
            table_exists = target_cur.fetchone()[0]
            
            if not table_exists:
                target_cur.execute(create_table_sql)
                target_conn.commit()
                logger.info(f"Created table {table_name} in target database")
            else:
                logger.info(f"Table {table_name} already exists in target database")
                
    except psycopg2.Error as e:
        logger.error(f"Database error ensuring table exists: {table_name}: {str(e)}")
        target_conn.rollback()
        raise
    except Exception as e:
        logger.error(f"Failed to ensure table exists: {table_name}: {str(e)}")
        raise

@lru_cache(maxsize=128)
def get_database_size(conn: connection) -> str:
    """
    Get formatted database size with caching
    
    Args:
        conn: Database connection
        
    Returns:
        Formatted size string (e.g. "1.23 GB")
        
    Raises:
        psycopg2.Error: On database errors
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database()) as size")
            size_bytes = cur.fetchone()[0]
            return SizeFormatter.format_size(size_bytes)
    except psycopg2.Error as e:
        logger.error(f"Database error getting size: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error getting database size: {str(e)}")
        raise

@lru_cache(maxsize=256)
def get_table_size(conn: connection, table_name: str) -> str:
    """
    Get formatted table size with caching
    
    Args:
        conn: Database connection
        table_name: Name of table to measure
        
    Returns:
        Formatted size string (e.g. "1.23 MB")
        
    Raises:
        psycopg2.Error: On database errors
        ValueError: On invalid table name
    """
    if not table_name.isalnum() and not all(c in '_' for c in table_name):
        raise ValueError(f"Invalid table name: {table_name}")
        
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_total_relation_size(%s) as size",
                (table_name,)
            )
            size_bytes = cur.fetchone()[0]
            return SizeFormatter.format_size(size_bytes)
    except psycopg2.Error as e:
        logger.error(f"Database error getting table size: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error getting table size: {str(e)}")
        raise

def setup_logging(
    log_dir: str = 'api/logs',
    log_file: str = 'dbmigrate.log',
    max_bytes: int = 10*1024*1024,
    backup_count: int = 5
) -> logging.Logger:
    """
    Set up logging with file and console handlers
    
    Args:
        log_dir: Directory for log files
        log_file: Name of log file
        max_bytes: Maximum size of each log file
        backup_count: Number of backup files to keep
        
    Returns:
        Configured logger instance
    """
    # Create log directory
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    class MemoryFilter(logging.Filter):
        """Add memory usage information to log records"""
        def filter(self, record: logging.LogRecord) -> bool:
            try:
                process = psutil.Process(os.getpid())
                record.memory_usage = f"{process.memory_info().rss / 1024 / 1024:.2f}"
                return True
            except Exception:
                record.memory_usage = "N/A"
                return True

    # Configure formatters
    file_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s - Memory: %(memory_usage)s MB',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Set up file handler
    file_handler = RotatingFileHandler(
        log_path / log_file,
        maxBytes=max_bytes,
        backupCount=backup_count
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)
    file_handler.addFilter(MemoryFilter())
    
    # Set up console handler
    console = Console()
    console_handler = RichHandler(
        rich_tracebacks=True,
        console=console,
        show_time=True
    )
    console_handler.setLevel(logging.INFO)
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    # Remove any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# Initialize globalglobal variables
resource_monitor_active = True
logger = setup_logging()
tracemalloc.start()

class DatabaseMigrator:
    def __init__(self, source_params: Dict[str, str], target_params: Dict[str, str], 
                 batch_size: int = 10000, max_workers: int = 4):
        self.source_params = source_params
        self.target_params = target_params
        self.batch_size = batch_size
        self.max_workers = max_workers
        self.logger = logging.getLogger(__name__)
        self.console = Console()
        self.error_queue = Queue()
        
    @contextmanager
    def get_connection(self, params: Dict[str, str]) -> psycopg2.extensions.connection:
        """Context manager for database connections with retry logic"""
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                conn = psycopg2.connect(**params)
                conn.set_session(autocommit=False)
                yield conn
                return
            except psycopg2.Error as e:
                if attempt == max_retries - 1:
                    raise
                self.logger.warning(f"Connection attempt {attempt + 1} failed: {str(e)}")
                time.sleep(retry_delay)
                retry_delay *= 2
        
    def calculate_table_checksum(self, conn: psycopg2.extensions.connection, table_name: str) -> str:
        """Calculate SHA-256 checksum of table contents"""
        try:
            with conn.cursor() as cur:
                output = io.StringIO()
                cur.copy_expert(
                    f"COPY (SELECT * FROM {table_name} ORDER BY timestamp) TO STDOUT WITH CSV",
                    output
                )
                return hashlib.sha256(output.getvalue().encode()).hexdigest()
        except Exception as e:
            self.logger.error(f"Error calculating checksum for {table_name}: {str(e)}")
            return ""

    def migrate_table_batch(self, source_conn: psycopg2.extensions.connection,
                          target_conn: psycopg2.extensions.connection,
                          table_name: str, offset: int) -> int:
        """Migrate a batch of rows from source to target"""
        try:
            with source_conn.cursor() as source_cur, target_conn.cursor() as target_cur:
                source_cur.execute(f"""
                    SELECT * FROM {table_name}
                    ORDER BY timestamp
                    LIMIT {self.batch_size} OFFSET {offset}
                """)
                
                if not source_cur.rowcount:
                    return 0
                    
                output = io.StringIO()
                source_cur.copy_expert(f"COPY ({source_cur.query}) TO STDOUT WITH CSV", output)
                output.seek(0)
                
                temp_table = f"temp_{table_name}_{threading.get_ident()}"
                target_cur.execute(f"CREATE TEMP TABLE {temp_table} (LIKE {table_name})")
                target_cur.copy_expert(f"COPY {temp_table} FROM STDIN WITH CSV", output)
                
                target_cur.execute(f"""
                    INSERT INTO {table_name}
                    SELECT * FROM {temp_table} t
                    WHERE NOT EXISTS (
                        SELECT 1 FROM {table_name} m
                        WHERE m.timestamp = t.timestamp
                    )
                """)
                
                rows_inserted = target_cur.rowcount
                target_conn.commit()
                target_cur.execute(f"DROP TABLE {temp_table}")
                
                return rows_inserted
                
        except Exception as e:
            target_conn.rollback()
            raise

    def migrate_table(self, table_name: str, progress: Progress, task_id: int) -> TableInfo:
        """Migrate a single table with batching and progress tracking"""
        info = TableInfo(name=table_name)
        
        try:
            with self.get_connection(self.source_params) as source_conn, \
                 self.get_connection(self.target_params) as target_conn:
                
                # Get table statistics
                with source_conn.cursor() as cur:
                    cur.execute(f"SELECT COUNT(*) FROM {table_name}")
                    total_rows = cur.fetchone()[0]
                    progress.update(task_id, total=total_rows)
                    
                    info.source_rows = total_rows
                    info.source_size = self.get_table_size(source_conn, table_name)
                
                # Ensure table exists in target
                self.ensure_table_exists(source_conn, target_conn, table_name)
                
                # Migrate in batches
                offset = 0
                total_migrated = 0
                
                while True:
                    rows_inserted = self.migrate_table_batch(
                        source_conn, target_conn, table_name, offset
                    )
                    
                    if not rows_inserted:
                        break
                        
                    total_migrated += rows_inserted
                    offset += self.batch_size
                    progress.update(task_id, advance=rows_inserted)
                
                # Verify migration
                source_checksum = self.calculate_table_checksum(source_conn, table_name)
                target_checksum = self.calculate_table_checksum(target_conn, table_name)
                
                info.checksum = source_checksum
                info.success = source_checksum == target_checksum
                info.target_rows = self.get_table_stats(target_conn, table_name)
                info.target_size = self.get_table_size(target_conn, table_name)
                
        except Exception as e:
            error_msg = f"Error migrating {table_name}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            info.error_message = error_msg
            self.error_queue.put((table_name, error_msg))
            
        return info

    def migrate_all_tables(self, tables: List[str]) -> Tuple[List[TableInfo], str, str]:
        """Migrate all tables using thread pool"""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self.console
        ) as progress:
            
            tables_info = []
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_table = {
                    executor.submit(
                        self.migrate_table,
                        table,
                        progress,
                        progress.add_task(f"[cyan]Migrating {table}", total=None)
                    ): table for table in tables
                }
                
                for future in as_completed(future_to_table):
                    table_info = future.result()
                    tables_info.append(table_info)
            
            # Get final database sizes
            with self.get_connection(self.source_params) as conn:
                source_size = self.get_database_size(conn)
            with self.get_connection(self.target_params) as conn:
                target_size = self.get_database_size(conn)
                
            return tables_info, source_size, target_size

    def print_error_summary(self):
        """Print summary of any errors that occurred during migration"""
        if not self.error_queue.empty():
            error_table = Table(title="Migration Errors", show_header=True)
            error_table.add_column("Table", style="cyan")
            error_table.add_column("Error", style="red")
            
            while not self.error_queue.empty():
                table, error = self.error_queue.get()
                error_table.add_row(table, error)
            
            self.console.print("\n")
            self.console.print(error_table)

    def read_db_config(file_path):
        """Read database configuration from file"""
        logger.info(f"Reading database configuration from {file_path}")
        try:
            config = configparser.ConfigParser()
            config.read(file_path)
            return {
                'dbname': config['postgresql']['database'],
                'user': config['postgresql']['user'],
                'password': config['postgresql']['password'],
                'host': config['postgresql']['host'],
                'port': config['postgresql']['port']
            }
        except Exception as e:
            logger.error(f"Failed to read database configuration: {str(e)}")
            raise

    # Include other necessary utility methods (get_table_size, ensure_table_exists, etc.)
    # with appropriate error handling and logging

def main():
    """Main execution function with improved error handling and reporting"""
    start_time = datetime.now()
    logger = logging.getLogger(__name__)
    console = Console()
    
    try:
        # Read configuration
        source_params = read_db_config('api/ini/optiondata.ini')
        target_params = read_db_config('api/ini/test.ini')
        
        # Get list of tables
        with psycopg2.connect(**source_params) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                """)
                tables = [table[0] for table in cur.fetchall()]
        
        # Initialize migrator
        migrator = DatabaseMigrator(
            source_params=source_params,
            target_params=target_params,
            batch_size=10000,
            max_workers=4
        )
        
        # Perform migration
        tables_info, source_size, target_size = migrator.migrate_all_tables(tables)
        
        # Print summaries
        migrator.print_error_summary()
        print_migration_summary(tables_info, source_size, target_size)
        
        duration = datetime.now() - start_time
        logger.info(f"Migration completed in {duration}")
        console.print(f"\n[bold green]Migration completed in {duration}![/bold green]")
        
    except Exception as e:
        logger.error("Migration failed", exc_info=True)
        console.print(f"[bold red]Migration failed: {str(e)}[/bold red]")
        sys.exit(1)

if __name__ == "__main__":
    main()
