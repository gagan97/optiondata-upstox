import psycopg2
import configparser
import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
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

# Initialize Rich console
console = Console()

def setup_logging():
    """Set up logging with both file and console handlers"""
    log_dir = os.path.join('api', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    class MemoryFilter(logging.Filter):
        def filter(self, record):
            process = psutil.Process(os.getpid())
            record.memory_usage = f"{process.memory_info().rss / 1024 / 1024:.2f}"
            return True

    file_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s - Memory: %(memory_usage)s MB',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler with rotation
    log_file = os.path.join(log_dir, 'dbmigrate.log')
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)
    file_handler.addFilter(MemoryFilter())
    
    # Console handler
    console_handler = RichHandler(rich_tracebacks=True, console=console)
    console_handler.setLevel(logging.INFO)
    
    # Root logger configuration
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# Global variables
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

def get_table_schema(conn, table_name):
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

def ensure_table_exists(source_conn, target_conn, table_name):
    """Ensure table exists in target database"""
    logger.info(f"Ensuring table exists in target database: {table_name}")
    try:
        create_table_sql = get_table_schema(source_conn, table_name)
        with target_conn.cursor() as target_cur:
            target_cur.execute(create_table_sql)
            target_conn.commit()
        logger.info(f"Table {table_name} created/verified in target database")
    except Exception as e:
        logger.error(f"Failed to ensure table exists: {table_name}: {str(e)}")
        raise

def get_database_size(conn):
    """Get formatted database size"""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database()) as size")
            size_bytes = cur.fetchone()[0]
            
            units = ['B', 'KB', 'MB', 'GB', 'TB']
            index = 0
            size = float(size_bytes)
            while size >= 1024 and index < len(units) - 1:
                size /= 1024
                index += 1
            return f"{size:.2f} {units[index]}"
    except Exception as e:
        logger.error(f"Error getting database size: {str(e)}")
        raise

def get_table_size(conn, table_name):
    """Get formatted table size"""
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT pg_total_relation_size('{table_name}') as size")
            size_bytes = cur.fetchone()[0]
            
            units = ['B', 'KB', 'MB', 'GB', 'TB']
            index = 0
            size = float(size_bytes)
            while size >= 1024 and index < len(units) - 1:
                size /= 1024
                index += 1
            return f"{size:.2f} {units[index]}"
    except Exception as e:
        logger.error(f"Error getting table size for {table_name}: {str(e)}")
        raise

def get_table_stats(conn, table_name):
    """Get row count for table"""
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table_name}")
            return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"Error getting table stats for {table_name}: {str(e)}")
        raise

def print_migration_summary(tables_info, source_size, target_size):
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

def copy_table_data(source_conn, target_conn, table_name, progress, task_id):
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
                
                output = io.StringIO()
                source_cur.copy_expert(f"COPY {table_name} TO STDOUT WITH CSV", output)
                output.seek(0)
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
                
                progress.update(task_id, advance=source_rows)
                target_rows = get_table_stats(target_conn, table_name)
                target_size = get_table_size(target_conn, table_name)
                
                final_memory = psutil.Process(os.getpid()).memory_info().rss
                memory_diff = (final_memory - initial_memory) / 1024 / 1024
                logger.info(f"Memory usage for {table_name}: {memory_diff:.2f}MB")
                
                return {
                    'table': table_name,
                    'source_rows': source_rows,
                    'target_rows': target_rows,
                    'source_size': source_size,
                    'target_size': target_size,
                    'success': True
                }
                
        finally:
            monitor.stop_flag.set()
            monitor.join()
            
    except Exception as e:
        error_msg = f"Error copying table {table_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        # Log detailed error information
        logger.error(f"Thread state for {thread_name}:")
        frame = sys._current_frames().get(threading.current_thread().ident)
        if frame:
            logger.error(''.join(traceback.format_stack(frame)))
        
        # Try to log database connection states
        try:
            logger.error(f"Source connection status: {source_conn.status}")
            logger.error(f"Target connection status: {target_conn.status}")
        except:
            pass
        
        target_conn.rollback()
        return {
            'table': table_name,
            'source_rows': source_rows if 'source_rows' in locals() else 0,
            'target_rows': 0,
            'source_size': source_size if 'source_size' in locals() else '0 B',
            'target_size': '0 B',
            'success': False
        }

def process_tables(source_params, target_params, tables):
    """Process all tables with threading"""
    logger.info("Starting table processing")
    source_conn = psycopg2.connect(**source_params)
    target_conn = psycopg2.connect(**target_params)
    
    source_total_size = get_database_size(source_conn)
    logger.info(f"Source database total size: {source_total_size}")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        
        tables_info = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = []
            
            for table in tables:
                task_id = progress.add_task(f"[cyan]Migrating {table}", total=None)
                future = executor.submit(
                    copy_table_data,
                    psycopg2.connect(**source_params),
                    psycopg2.connect(**target_params),
                    table,
                    progress,
                    task_id
                )
                futures.append((future, table))
            
            for future, _ in futures:
                tables_info.append(future.result())
    
    target_total_size = get_database_size(target_conn)
    logger.info(f"Target database total size: {target_total_size}")
    
    source_conn.close()
    target_conn.close()
    logger.info("Database connections closed")
    
    return tables_info, source_total_size, target_total_size

def main():
    """Main execution function"""
    logger.info("Starting database migration")
    
    # Start resource monitoring
    log_system_resources()
    
    try:
        with console.status("[bold green]Reading configuration...") as status:
            option_chain_params = read_db_config(os.path.join('api', 'ini', 'optiondata.ini'))
            option_data_params = read_db_config(os.path.join('api', 'ini', 'test.ini'))
            
            # Test database connections
            for params, desc in [(option_chain_params, "source"), (option_data_params, "target")]:
                try:
                    with psycopg2.connect(**params) as conn:
                        with conn.cursor() as cur:
                            cur.execute("SELECT 1")
                except Exception as e:
                    logger.critical(f"Failed to connect to {desc} database: {str(e)}")
                    raise
            
            with psycopg2.connect(**option_chain_params) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT table_name 
                        FROM information_schema.tables 
                        WHERE table_schema = 'public'
                    """)
                    tables = [table[0] for table in cur.fetchall()]
            
            status.update("[bold green]Configuration loaded successfully!")
            logger.info(f"Found {len(tables)} tables to migrate")

        console.print(Panel.fit(
            f"[bold]Found {len(tables)} tables to migrate[/bold]",
            border_style="blue"
        ))
        
        tables_info, source_size, target_size = process_tables(option_chain_params, option_data_params, tables)
        print_migration_summary(tables_info, source_size, target_size)

    except Exception as e:
        error_msg = f"Migration failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        # Log final system state
        process = psutil.Process(os.getpid())
        logger.critical(f"Final process state on error - "
                      f"Memory: {process.memory_info().rss / 1024 / 1024:.2f}MB, "
                      f"CPU: {process.cpu_percent()}%, "
                      f"Threads: {threading.active_count()}")
        
        console.print(f"[bold red]{error_msg}[/bold red]")
        sys.exit(1)

if __name__ == "__main__":
    start_time = datetime.now()
    logger.info("Database Migration Tool Started")
    logger.info("=" * 50)
    
    console.print("[bold blue]Database Migration Tool[/bold blue]")
    console.print("=" * 50)
    
    try:
        main()
        end_time = datetime.now()
        duration = end_time - start_time
        logger.info(f"Migration completed successfully in {duration}")
        console.print(f"\n[bold green]Migration completed successfully in {duration}![/bold green]")
    except KeyboardInterrupt:
        logger.warning("Migration interrupted by user")
        console.print("\n[bold yellow]Migration interrupted by user[/bold yellow]")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        logger.error("Full traceback:", exc_info=True)
        console.print("\n[bold red]Migration failed with unexpected error![/bold red]")
        sys.exit(1)
    finally:
        # Clean up resources
        resource_monitor_active = False
        tracemalloc.stop()
