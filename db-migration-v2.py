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

console = Console()

def read_db_config(file_path):
    config = configparser.ConfigParser()
    config.read(file_path)
    return {
        'dbname': config['postgresql']['database'],
        'user': config['postgresql']['user'],
        'password': config['postgresql']['password'],
        'host': config['postgresql']['host'],
        'port': config['postgresql']['port']
    }

def format_size(size_bytes):
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    index = 0
    size = float(size_bytes)
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.2f} {units[index]}"

def get_database_stats(conn):
    with conn.cursor() as cur:
        # Get database size
        cur.execute("SELECT pg_database_size(current_database())")
        total_size = cur.fetchone()[0]
        
        # Get number of active connections
        cur.execute("SELECT count(*) FROM pg_stat_activity")
        connections = cur.fetchone()[0]
        
        # Get database uptime
        cur.execute("SELECT pg_postmaster_start_time()")
        start_time = cur.fetchone()[0]
        uptime = datetime.now() - start_time
        
        return {
            'size': format_size(total_size),
            'connections': connections,
            'uptime': str(uptime).split('.')[0]  # Remove microseconds
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
    table = Table(
        title="Migration Progress",
        show_header=True,
        header_style="bold magenta",
        box=box.ROUNDED
    )
    
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
    
    return table

def create_summary_panel(tables_info, source_size, target_size):
    successful = sum(1 for info in tables_info if info['success'])
    total_tables = len(tables_info)
    
    total_source_rows = sum(info['source_rows'] for info in tables_info)
    total_target_rows = sum(info['target_rows'] for info in tables_info)
    
    summary = Table.grid()
    summary.add_column(style="cyan")
    summary.add_column(style="yellow")
    
    summary.add_row("Total Tables:", f"{total_tables}")
    summary.add_row("Successfully Migrated:", f"{successful}/{total_tables}")
    summary.add_row("Total Source Rows:", f"{total_source_rows:,}")
    summary.add_row("Total Target Rows:", f"{total_target_rows:,}")
    summary.add_row("Source Database Size:", source_size)
    summary.add_row("Target Database Size:", target_size)
    
    return Panel(
        summary,
        title="[bold]Migration Summary[/bold]",
        border_style="green"
    )

def update_dashboard(tables_info, source_stats, target_stats, source_size, target_size):
    layout = Layout()
    
    layout.split_column(
        Layout(name="upper"),
        Layout(name="lower", ratio=2)
    )
    
    layout["upper"].split_row(
        Layout(create_status_panel(source_stats, target_stats), ratio=2),
        Layout(create_summary_panel(tables_info, source_size, target_size))
    )
    
    layout["lower"].update(create_progress_table(tables_info))
    
    return layout

def main():
    try:
        console.clear()
        console.print("[bold blue]Database Migration Dashboard[/bold blue]", justify="center")
        console.print("=" * console.width, style="blue")
        
        with console.status("[bold green]Reading configuration...") as status:
            source_params = read_db_config(os.path.join('api', 'ini', 'OptionChain.ini'))
            target_params = read_db_config(os.path.join('api', 'ini', 'optiondata.ini'))
            
            with psycopg2.connect(**source_params) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT table_name 
                        FROM information_schema.tables 
                        WHERE table_schema = 'public'
                    """)
                    tables = [table[0] for table in cur.fetchall()]
        
        with Live(auto_refresh=False) as live:
            # Initialize connections for stats
            source_conn = psycopg2.connect(**source_params)
            target_conn = psycopg2.connect(**target_params)
            
            source_stats = get_database_stats(source_conn)
            target_stats = get_database_stats(target_conn)
            source_size = source_stats['size']
            
            tables_info = []
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = []
                
                for table in tables:
                    future = executor.submit(
                        copy_table_data,
                        psycopg2.connect(**source_params),
                        psycopg2.connect(**target_params),
                        table
                    )
                    futures.append((future, table))
                
                for future, _ in futures:
                    result = future.result()
                    tables_info.append(result)
                    
                    # Update dashboard after each table
                    target_stats = get_database_stats(target_conn)
                    dashboard = update_dashboard(
                        tables_info,
                        source_stats,
                        target_stats,
                        source_size,
                        target_stats['size']
                    )
                    live.update(dashboard, refresh=True)
            
            source_conn.close()
            target_conn.close()

    except Exception as e:
        console.print(f"[bold red]Migration failed: {str(e)}[/bold red]")
        raise

if __name__ == "__main__":
    main()
    console.print("\n[bold green]Migration completed successfully![/bold green]")
