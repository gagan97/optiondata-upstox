import psycopg2
import configparser
import os
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import io
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.table import Table
from rich.layout import Layout
from rich.live import Live
from rich.align import Align
from rich.text import Text
from rich import box
import pytz

# Set up logging
log_dir = os.path.join('api', 'db-migration')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'db-migration.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
#        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)
console = Console()

# Create a separate console handler for errors only
error_console_handler = logging.StreamHandler()
error_console_handler.setLevel(logging.ERROR)
error_formatter = logging.Formatter('%(levelname)s: %(message)s')
error_console_handler.setFormatter(error_formatter)
logger.addHandler(error_console_handler)

def read_db_config(file_path):
    try:
        config = configparser.ConfigParser()
        config.read(file_path)
        db_config = {
            'dbname': config['postgresql']['database'],
            'user': config['postgresql']['user'],
            'password': config['postgresql']['password'],
            'host': config['postgresql']['host'],
            'port': config['postgresql']['port']
        }
        logger.info(f"Successfully read configuration from {file_path}")
        return db_config
    except Exception as e:
        logger.error(f"Error reading configuration from {file_path}: {str(e)}")
        raise

def format_size(size_bytes):
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    index = 0
    size = float(size_bytes)
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.2f} {units[index]}"

def create_db_info_panel(db_stats, title):
    """Create a panel showing database information"""
    table = Table(show_header=False, box=box.ROUNDED, padding=(0, 1))
    table.add_column("Metric", style="cyan", width=20)
    table.add_column("Value", style="green")
    
    table.add_row("Size", db_stats['size'])
    table.add_row("Active Connections", str(db_stats['connections']))
    table.add_row("Uptime", db_stats['uptime'])
    table.add_row("Host", db_stats['host'])
    table.add_row("Database", db_stats['dbname'])
    
    return Panel(
        Align.center(table, vertical="middle"),
        title=f"[bold]{title}[/bold]",
        border_style="bright_blue",
        padding=(1, 1)
    )

def get_database_stats(conn, db_config=None):
    """
    Get database statistics and connection information
    Args:
        conn: Database connection object
        db_config: Optional dictionary containing database configuration
    """
    try:
        host = db_config['host'] if db_config else 'unknown'
        dbname = db_config['dbname'] if db_config else 'unknown'
        
        with conn.cursor() as cur:
            # Get database size
            cur.execute("SELECT pg_database_size(current_database())")
            total_size = cur.fetchone()[0]
            
            # Get number of active connections
            cur.execute("SELECT count(*) FROM pg_stat_activity")
            connections = cur.fetchone()[0]
            
            # Get database uptimeGet database uptime
            cur.execute("SELECT pg_postmaster_start_time()")
            start_time = cur.fetchone()[0]
            
            if start_time.tzinfo is None:
                start_time = pytz.UTC.localize(start_time)
            
            current_time = datetime.now(pytz.UTC)
            uptime = current_time - start_time
            
            stats = {
                'size': format_size(total_size),
                'connections': connections,
                'uptime': str(uptime).split('.')[0],
                'host': host,
                'dbname': dbname
            }
            
            return stats
    except Exception as e:
        logger.error(f"Error getting database stats: {str(e)}")
        raise

def copy_table_data(source_conn, target_conn, table_name, progress):
    try:
        task_id = progress.add_task(f"[cyan]Migrating {table_name}", total=100)
        logger.info(f"Starting migration for table: {table_name}")
        
        with source_conn.cursor() as source_cur, target_conn.cursor() as target_cur:
            # Get source table statistics
            source_cur.execute(f"SELECT COUNT(*) FROM {table_name}")
            source_rows = source_cur.fetchone()[0]
            progress.update(task_id, advance=10)
            
            # Create temporary table (previous code remains the same)
            source_cur.execute("""
                SELECT column_name, data_type, character_maximum_length 
                FROM information_schema.columns 
                WHERE table_name = %s
            """, (table_name,))
            
            columns_def = ', '.join(
                f"{col[0]} {col[1]}" + (f"({col[2]})" if col[2] else '')
                for col in source_cur.fetchall()
            )
            
            temp_table = f"temp_{table_name}"
            target_cur.execute(f"CREATE TEMP TABLE {temp_table} ({columns_def})")
            progress.update(task_id, advance=20)
            
            # Copy data with progress updatesCopy data with progress updates
            output = io.StringIO()
            source_cur.copy_expert(f"COPY {table_name} TO STDOUT WITH CSV", output)
            progress.update(task_id, advance=30)
            
            output.seek(0)
            target_cur.copy_expert(f"COPY {temp_table} FROM STDIN WITH CSV", output)
            progress.update(task_id, advance=20)
            
            # Insert new records
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
            progress.update(task_id, advance=20)
            
            # Get final statisticsGet final statistics
            source_cur.execute(f"SELECT pg_total_relation_size('{table_name}')")
            source_size = format_size(source_cur.fetchone()[0])
            
            target_cur.execute(f"SELECT pg_total_relation_size('{table_name}')")
            target_size = format_size(target_cur.fetchone()[0])
            
            progress.update(task_id, completed=100)
            
            return {
                'table': table_name,
                'source_rows': source_rows,
                'target_rows': rows_inserted,
                'source_size': source_size,
                'target_size': target_size,
                'success': True
            }
            
    except Exception as e:
        logger.error(f"Error copying {table_name}: {str(e)}")
        progress.update(task_id, completed=True, visible=False)
        return {
            'table': table_name,
            'source_rows': source_rows if 'source_rows' in locals() else 0,
            'target_rows': 0,
            'source_size': '0 B',
            'target_size': '0 B',
            'success': False
        }

def create_status_panel(source_stats, target_stats):
    table = Table(show_header=True, box=box.ROUNDED)
    table.add_column("Metric", style="cyan")
    table.add_column("Source DB", style="green")
    table.add_column("Target DB", style="blue")
    
    table.add_row("Total Size", source_stats['size'], target_stats['size'])
    table.add_row("Connections", str(source_stats['connections']), str(target_stats['connections']))
    table.add_row("Uptime", source_stats['uptime'], target_stats['uptime'])
    
    return Panel(
        Align.center(table),
        title="[bold]Database Status[/bold]",
        border_style="bright_blue"
    )

def create_progress_table(tables_info):
    """Create a table showing migration progress"""
    table = Table(
        show_header=True,
        header_style="bold magenta",
        box=box.ROUNDED,
        padding=(0, 1),
        width=None  # Allow table to take full width
    )

    table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
    
    table.add_column("Table Name", style="cyan", width=30)
    table.add_column("Source Rows", justify="right", style="green")
    table.add_column("Target Rows", justify="right", style="blue")
    table.add_column("Source Size", justify="right", style="green")
    table.add_column("Target Size", justify="right", style="blue")
    table.add_column("Completion", justify="center", style="yellow", width=10)
    table.add_column("Status", style="yellow", width=10)
    
    for info in tables_info:
        progress = "⬢" * int((info['target_rows'] / max(info['source_rows'], 1)) * 10)
        progress = progress.ljust(10, "⬡")
        
        status = "✓" if info['success'] else "✗"
        status_style = "bold green" if info['success'] else "bold red"
        
        table.add_row(
            info['table'],
            str(info['source_rows']),
            str(info['target_rows']),
            info['source_size'],
            info['target_size'],
            progress,
            Text(status, style=status_style)
        )
    
    return Panel(table, border_style="bright_blue", padding=(1, 1))

def print_to_console(message, style=""):
    """Utility function to print to console with Rich styling"""
    if style:
        console.print(message, style=style)
    else:
        console.print(message)

def main():
    logger.info("Starting database migration process")
    try:
        console.clear()
        
        console.print(Align.center("[bold blue]Database Migration Dashboard[/bold blue]"))
        console.print(Align.center("=" * min(console.width, 100)))
        
        source_params = read_db_config(os.path.join('api', 'ini', 'OptionChain.ini'))
        target_params = read_db_config(os.path.join('api', 'ini', 'optiondata.ini'))
        
        with Live(auto_refresh=False, vertical_overflow="visible") as live:
            layout = Layout()

            # Create a more compact layout
            layout.split_column(
                Layout(name="header", size=15),
                Layout(name="table", size=20),
                Layout(name="progress")
            )
            
            layout["db_info"].split_row(
                Layout(name="source_db"),
                Layout(name="target_db")
            )

            # Initial table display
            layout["table"].update(create_progress_table([]))
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                console=console,
                expand=True,
                transient=True  # This will make completed tasks disappear
            
            ) as progress:
                with ThreadPoolExecutor(max_workers=4) as executor:
                    tables = get_tables(source_conn)
                    futures = []
                    tables_info = []
                    
                    for table in tables:
                        future = executor.submit(
                            copy_table_data,
                            psycopg2.connect(**source_params),
                            psycopg2.connect(**target_params),
                            table,
                            progress
                        )
                        futures.append((future, table))
                    
                    for future, table in futures:
                        result = future.result()
                        tables_info.append(result)
                        layout["table"].update(create_progress_table(tables_info))
                        live.update(layout)
            
            source_conn.close()
            target_conn.close()

    except Exception as e:
        logger.error(f"Migration failed: {str(e)}", exc_info=True)
        raise

def get_tables(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        return [table[0] for table in cur.fetchall()]

if __name__ == "__main__":
    try:
        main()
        console.print("\n[bold green]Migration completed successfully![/bold green]")
    except Exception as e:
        console.print(f"\n[bold red]Migration failed: {str(e)}[/bold red]")
