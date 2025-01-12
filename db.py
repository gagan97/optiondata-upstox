import psycopg2
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
from psycopg2.extensions import connection
from functools import lru_cache

# Initialize Rich console
console = Console()

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

# Initialize global variables
resource_monitor_active = True
logger = setup_logging()
tracemalloc.start()

def log_system_resources():
    """Periodically log system resource usage"""
    if not resource_monitor_active:
        return
        
    try:
        process = psutil.Process(os.getpid())
        cpu_percent = process.cpu_percent()
        memory_info = process.memory_info()
        gc_counts = gc.get_count()
        current, peak = tracemalloc.get_traced_memory()
        
        logger.debug(
            f"Resource Usage - CPU: {cpu_percent}%, "
            f"Memory: {memory_info.rss / 1024 / 1024:.2f}MB, "
            f"Peak Memory: {peak / 1024 / 1024:.2f}MB, "
            f"GC Counts: {gc_counts}, "
            f"Active Threads: {threading.active_count()}"
        )
        
        if resource_monitor_active:
            Timer(60.0, log_system_resources).start()
    except Exception as e:
        logger.error(f"Error in resource monitoring: {str(e)}")

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

class ConnectionMonitor(threading.Thread):
    """Monitor database connections"""
    def __init__(self, source_conn, target_conn):
        super().__init__()
        self.source_conn = source_conn
        self.target_conn = target_conn
        self.daemon = True
        self.stop_flag = threading.Event()

    def run(self):
        while not self.stop_flag.is_set():
            try:
                self._check_connection(self.source_conn, "source")
                self._check_connection(self.target_conn, "target")
                self.stop_flag.wait(30)
            except Exception as e:
                logger.error(f"Error in connection monitoring: {str(e)}")

    def _check_connection(self, conn, name):
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        except Exception as e:
            logger.error(f"Database connection lost ({name}): {str(e)}")

def signal_handler(signum, frame):
    """Handle system signals"""
    signal_name = signal.Signals(signum).name
    logger.critical(f"Received signal {signal_name} ({signum})")
    
    process = psutil.Process(os.getpid())
    logger.critical(
        f"Final process state - "
        f"Memory: {process.memory_info().rss / 1024 / 1024:.2f}MB, "
        f"CPU: {process.cpu_percent()}%, "
        f"Threads: {threading.active_count()}"
    )
    
    for thread in threading.enumerate():
        if thread != threading.current_thread():
            logger.critical(f"Stack trace for thread {thread.name}:")
            frame = sys._current_frames().get(thread.ident)
            if frame:
                logger.critical(''.join(traceback.format_stack(frame)))
    
    global resource_monitor_active
    resource_monitor_active = False
    sys.exit(1)

# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)
if hasattr(signal, 'SIGQUIT'):
    signal.signal(signal.SIGQUIT, signal_handler)

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

def get_table_schema(conn: connection, table_name: str) -> str:
    """Get table schema as CREATE TABLE statement"""
    logger.debug(f"Getting schema for table: {table_name}")
    try:
        with conn.cursor() as cur:
            # Get column definitions
            cur.execute("""
                SELECT column_name, data_type, character_maximum_length,
                       is_nullable, column_default
                FROM information_schema.columns 
                WHERE table_name = %s
                ORDER BY ordinal_position
            """, (table_name,))
            
            columns = []
            for col in cur.fetchall():
                name, data_type, max_length, is_nullable, default = col
                column_def = f"{name} {data_type}"
                if max_length:
                    column_def += f"({max_length})"
                if default:
                    column_def += f" DEFAULT {default}"
                if is_nullable == 'NO':
                    column_def += " NOT NULL"
                columns.append(column_def)

            # Get primary key constraint
            cur.execute("""
                SELECT c.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage AS ccu 
                    ON ccu.constraint_name = tc.constraint_name
                JOIN information_schema.columns AS c 
                    ON c.table_name = tc.table_name 
                    AND c.column_name = ccu.column_name
                WHERE tc.constraint_type = 'PRIMARY KEY' 
                    AND tc.table_name = %s;
            """, (table_name,))
            
            pk_columns = [row[0] for row in cur.fetchall()]
            if pk_columns:
                columns.append(f"PRIMARY KEY ({', '.join(pk_columns)})")

            create_table_sql = f"CREATE TABLE IF NOT EXISTS {table_name} (\n    " + ",\n    ".join(columns) + "\n)"
            return create_table_sql
    except Exception as e:
        logger.error(f"Error getting schema for table {table_name}: {str(e)}")
        raise

def ensure_table_exists(source_conn: connection, target_conn: connection, 
                       table_name: str) -> None:
    """
    Ensure table exists in target database with proper schema
    """
    logger.info(f"Ensuring table exists in target database: {table_name}")
    
    try:
        # Updated table name validation to allow underscores and numbers
        if not all(c.isalnum() or c == '_' for c in table_name):
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
    """Get formatted database size with caching"""
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
    """Get formatted table size with caching"""
    if not all(c.isalnum() or c == '_' for c in table_name):
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

def quote_identifier(identifier: str) -> str:
    """Safely quote a table or column identifier for SQL"""
    return f'"{identifier}"'

def get_table_stats(conn: connection, table_name: str) -> int:
    """Get row count for table"""
    try:
        with conn.cursor() as cur:
            quoted_table = quote_identifier(table_name)
            cur.execute(f"SELECT COUNT(*) FROM {quoted_table}")
            return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"Error getting table stats for {table_name}: {str(e)}")
        raise

def print_migration_summary(tables_info: List[Dict], source_size: str, target_size: str) -> None:
    """Print migration summary table"""
    logger.info("Generating migration summary")
    table = Table(title="Migration Summary", show_header=True, header_style="bold magenta")
    table.add_column("Table Name", style="cyan")
    table.add_column("Source Rows", justify="right", style="green")
    table.add_column("Target Rows", justify="right", style="blue")
    table.add_column("Source Size", justify="right", style="green")
    table.add_column("Target Size", justify="right", style="blue")
    table.add_column("Status", style="yellow")
    
    total_source = total_target = 0
    
    for info in tables_info:
        status = "✅ Success" if info['success'] else "❌ Failed"
        logger.info(f"Table {info['table']}: {status}")
        
        table.add_row(
            info['table'],
            str(info['source_rows']),
            str(info['target_rows']),
            info['source_size'],
            info['target_size'],
            status
        )
        total_source += info['source_rows']
        total_target += info['target_rows']
    
    table.add_row(
        "Total", 
        str(total_source), 
        str(total_target),
        source_size,
        target_size,
        "✨ Complete",
        style="bold"
    )
    
    console.print("\n")
    console.print(table)

def copy_table_data(
    source_conn: connection,
    target_conn: connection,
    table_name: str,
    progress: Progress,
    task_id: int
) -> Dict[str, Any]:
    """Copy data from source to target table"""
    thread_name = threading.current_thread().name
    logger.info(f"Starting data migration for table: {table_name} in thread {thread_name}")
    
    try:
        initial_memory = psutil.Process(os.getpid()).memory_info().rss
        
        monitor = ConnectionMonitor(source_conn, target_conn)
        monitor.start()
        
        try:
            ensure_table_exists(source_conn, target_conn, table_name)

            with source_conn.cursor() as source_cur, target_conn.cursor() as target_cur:
                source_rows = get_table_stats(source_conn, table_name)
                progress.update(task_id, total=source_rows)
                source_size = get_table_size(source_conn, table_name)
                
                # Create temporary table for staging
                temp_table = f"temp_{table_name}"
                source_cur.execute("""
                    SELECT column_name, data_type, character_maximum_length 
                    FROM information_schema.columns 
                    WHERE table_name = %s
                    ORDER BY ordinal_position
                """, (table_name,))
                
                columns_def = ', '.join(
                    f"{col[0]} {col[1]}" + (f"({col[2]})" if col[2] else '')
                    for col in source_cur.fetchall()
                )
                
                target_cur.execute(f"DROP TABLE IF EXISTS {temp_table}")
                target_cur.execute(f"CREATE TEMP TABLE {temp_table} ({columns_def})")
                
                # Copy data using CSV format for better performance
                output = io.StringIO()
                source_cur.copy_expert(f"COPY {table_name} TO STDOUT WITH CSV", output)
                output.seek(0)
                target_cur.copy_expert(f"COPY {temp_table} FROM STDIN WITH CSV", output)
                
                # Insert only new records
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
                
                progress.update(task_id, advance=source_rows)
                target_rows = get_table_stats(target_conn, table_name)
                target_size = get_table_size(target_conn, table_name)
                
                final_memory = psutil.Process(os.getpid()).memory_info().rss
                memory_diff = (final_memory - initial_memory) / 1024 / 1024
                logger.info(f"Memory usage for {table_name}: {memory_diff:.2f}MB")
                
                monitor.stop_flag.set()
                monitor.join()
                
                return {
                    'table': table_name,
                    'source_rows': source_rows,
                    'target_rows': target_rows,
                    'source_size': source_size,
                    'target_size': target_size,
                    'rows_inserted': rows_inserted,
                    'success': True
                }
                
        except Exception as e:
            logger.error(f"Error copying data for table {table_name}: {str(e)}")
            if monitor.is_alive():
                monitor.stop_flag.set()
                monitor.join()
            raise
            
    except Exception as e:
        return {
            'table': table_name,
            'source_rows': 0,
            'target_rows': 0,
            'source_size': '0 B',
            'target_size': '0 B',
            'rows_inserted': 0,
            'success': False,
            'error': str(e)
        }

def get_tables_to_migrate(conn: connection) -> List[str]:
    """Get list of tables to migrate"""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error getting tables list: {str(e)}")
        raise

def main():
    """Main migration function"""
    logger.info("Database Migration Tool Started")
    logger.info("=" * 50)
    
    try:
        logger.info("Starting database migration")
        
        # Start resource monitoring
        log_system_resources()
        
        # Read configurations
        source_config = read_db_config('api/ini/optiondata.ini')
        target_config = read_db_config('api/ini/test.ini')
        
        # Test database connections
        source_conn = target_conn = None
        for config, name in [(source_config, "source"), (target_config, "target")]:
            try:
                # Convert DatabaseConfig to dict before connecting
                config_dict = config.to_dict()
                with psycopg2.connect(**config_dict) as conn:
                    db_size = get_database_size(conn)
                    logger.info(f"Successfully connected to {name} database (Size: {db_size})")
                    
                    if name == "source":
                        source_conn = conn
                    else:
                        target_conn = conn
            except Exception as e:
                logger.critical(f"Failed to connect to {name} database: {str(e)}")
                raise
        
        # Get tables to migrate
        tables = get_tables_to_migrate(source_conn)
        if not tables:
            logger.warning("No tables found to migrate")
            return
            
        logger.info(f"Found {len(tables)} tables to migrate")
        
        # Set up progress tracking
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn()
        )
        
        tables_info = []
        with progress:
            # Create progress bars for each table
            tasks = {
                table: progress.add_task(f"Migrating {table}", total=None)
                for table in tables
            }
            
            # Use thread pool for parallel migration
            with ThreadPoolExecutor(max_workers=min(4, len(tables))) as executor:
                futures = []
                for table in tables:
                    future = executor.submit(
                        copy_table_data,
                        source_conn,
                        target_conn,
                        table,
                        progress,
                        tasks[table]
                    )
                    futures.append(future)
                
                # Wait for all migrations to complete
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        tables_info.append(result)
                    except Exception as e:
                        logger.error(f"Migration task failed: {str(e)}")
        
        # Print final summary
        source_size = get_database_size(source_conn)
        target_size = get_database_size(target_conn)
        print_migration_summary(tables_info, source_size, target_size)
        
    except Exception as e:
        logger.error(f"Migration failed: {str(e)}")
        console.print_exception()
        logger.critical(
            f"Final process state on error - "
            f"Memory: {psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024:.2f}MB, "
            f"CPU: {psutil.Process(os.getpid()).cpu_percent()}%, "
            f"Threads: {threading.active_count()}"
        )
        sys.exit(1)
    finally:
        # Clean up connections if they exist
        if 'source_conn' in locals() and source_conn:
            source_conn.close()
        if 'target_conn' in locals() and target_conn:
            target_conn.close()

if __name__ == '__main__':
    main()
