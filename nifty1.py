import sys
import requests
import psycopg2
from psycopg2 import sql
import logging
from logging.handlers import RotatingFileHandler
from configparser import ConfigParser
import os
from datetime import datetime, timedelta, time as dt_time 
import time as t
import schedule
import pytz
import holidays
from market_holiday_date_wise import market_holiday_date_wise
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.live import Live
from rich import box
from rich.text import Text

console = Console()

class ExpiryDateManager:
    def __init__(self):
        self.holidays_list = []
        self.current_expiries = []
        self.last_expiry_update = None
        self.initialize_holidays()
        
    def initialize_holidays(self):
        """Initialize holidays list once during startup"""
        with console.status("[bold green]Initializing holidays list..."):
            holiday_response = market_holiday_date_wise()
            if holiday_response and holiday_response.get('status') == 'success':
                self.holidays_list = [holiday['date'] for holiday in holiday_response.get('data', [])]
                console.print("[bold green]✓[/] Holidays list initialized")
            else:
                console.print("[bold red]✗[/] Failed to initialize holidays list")

    def should_update_expiries(self):
        """Check if expiries need to be updated (once per day)"""
        if not self.last_expiry_update:
            return True
        
        now = datetime.now(pytz.timezone('Asia/Kolkata'))
        return now.date() > self.last_expiry_update.date()

    def update_expiries(self):
        """Update expiry dates once per day"""
        if self.should_update_expiries():
            now = datetime.now(pytz.timezone('Asia/Kolkata'))
            self.current_expiries = self.get_all_thursday_expiries(now.year, now.month)
            self.last_expiry_update = now
            console.print("[bold green]✓[/] Expiry dates updated for the day")
            self.display_expiries(self.current_expiries)
        return self.current_expiries


    def get_valid_expiry(self, date):
        """Get valid expiry date accounting for holidays"""
        expiry_date = date
        while (expiry_date.strftime('%Y-%m-%d') in self.holidays_list or 
               expiry_date.weekday() > 4):
            expiry_date -= timedelta(days=1)
        return expiry_date

    def get_month_expiries(self, year, month, start_date):
        """Get all valid Thursday expiries for a specific month"""
        first_day = datetime(year, month, 1)
        if month == 12:
            next_month = datetime(year + 1, 1, 1)
        else:
            next_month = datetime(year, month + 1, 1)
        num_days = (next_month - timedelta(days=1)).day
        
        month_expiries = []
        for day in range(1, num_days + 1):
            current_date = datetime(year, month, day)
            if current_date.weekday() == 3:  # Thursday is 3
                expiry_date = self.get_valid_expiry(current_date.date())
                if expiry_date >= start_date and expiry_date not in month_expiries:
                    month_expiries.append(expiry_date)
        
        return month_expiries

    def get_all_thursday_expiries(self, year, month, today=None, num_expiries=5):
        """Get the next 5 Thursday expiries"""
        if today is None:
            today = datetime.now(pytz.timezone('Asia/Kolkata')).date()
        
        all_valid_expiries = []
        current_year = year
        current_month = month
        
        while len(all_valid_expiries) < num_expiries:
            first_day = datetime(current_year, current_month, 1)
            if current_month == 12:
                next_month = datetime(current_year + 1, 1, 1)
            else:
                next_month = datetime(current_year, current_month + 1, 1)
            num_days = (next_month - timedelta(days=1)).day
            
            for day in range(1, num_days + 1):
                current_date = datetime(current_year, current_month, day)
                if current_date.weekday() == 3:  # Thursday is 3
                    expiry_date = current_date.date()
                    while (expiry_date.strftime('%Y-%m-%d') in self.holidays_list or 
                           expiry_date.weekday() > 4):
                        expiry_date -= timedelta(days=1)
                    
                    if expiry_date >= today and expiry_date not in all_valid_expiries:
                        all_valid_expiries.append(expiry_date)
                        if len(all_valid_expiries) == num_expiries:
                            break
            
            if current_month == 12:
                current_month = 1
                current_year += 1
            else:
                current_month += 1
        
        all_valid_expiries.sort()
        return all_valid_expiries

    def display_expiries(self, expiries):
        """Display expiry dates in a rich formatted table"""
        table = Table(
            title="Available Expiry Dates",
            box=box.DOUBLE_EDGE,
            header_style="bold magenta",
            show_lines=True
        )
        
        table.add_column("Index", style="cyan", justify="center")
        table.add_column("Date", style="green")
        table.add_column("Day", style="yellow")
        
        for idx, expiry in enumerate(expiries, 1):
            day_name = expiry.strftime("%A")
            date_str = expiry.strftime("%Y-%m-%d")
            table.add_row(str(idx), date_str, day_name)
        
        console.print()
        console.print(table)
        console.print()

class DatabaseManager:
    def __init__(self, config_file="api/ini/test.ini", section="postgresql"):
        self.db_config = self.config_db(config_file, section)
        self.check_and_create_db()

    def config_db(self, filename, section):
        """Load database configuration from ini file"""
        parser = ConfigParser()
        parser.read(filename)
        db = {}
        if parser.has_section(section):
            db = dict(parser.items(section))
        else:
            raise Exception(f'Section {section} not found in {filename}')
        return db

    def check_and_create_db(self):
        """Check if database exists and create if it doesn't"""
        conn = None
        try:
            conn = psycopg2.connect(
                host=self.db_config['host'],
                user=self.db_config['user'],
                password=self.db_config['password'],
                port=self.db_config.get('port', 5432),
                database='postgres'
            )
            conn.autocommit = True
            cur = conn.cursor()
            
            # Check if database exists
            cur.execute(sql.SQL("SELECT 1 FROM pg_database WHERE datname = %s"), 
                       [self.db_config['database']])
            if not cur.fetchone():
                cur.execute(sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(self.db_config['database'])))
                logging.info(f"Database {self.db_config['database']} created.")
            
            cur.close()
        except Exception as e:
            logging.error(f"Database initialization error: {e}")
        finally:
            if conn:
                conn.close()

    def insert_data(self, table_name, data):
        """Insert data into specified table"""
        conn = None
        try:
            conn = psycopg2.connect(**self.db_config)
            cur = conn.cursor()

            # Create table if it doesn't exist
            create_table_query = f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                timestamp TIMESTAMP PRIMARY KEY,
                expiry DATE,
                strike_price NUMERIC,
                underlying_spot_price NUMERIC,
                call_ltp NUMERIC,
                call_close_price NUMERIC,
                call_volume INT,
                call_oi INT,
                call_bid_price NUMERIC,
                call_bid_qty INT,
                call_ask_price NUMERIC,
                call_ask_qty INT,
                call_vega NUMERIC,
                call_theta NUMERIC,
                call_gamma NUMERIC,
                call_delta NUMERIC,
                call_iv NUMERIC,
                put_ltp NUMERIC,
                put_close_price NUMERIC,
                put_volume INT,
                put_oi INT,
                put_bid_price NUMERIC,
                put_bid_qty INT,
                put_ask_price NUMERIC,
                put_ask_qty INT,
                put_vega NUMERIC,
                put_theta NUMERIC,
                put_gamma NUMERIC,
                put_delta NUMERIC,
                put_iv NUMERIC,
                pcr NUMERIC,
                underlying_key TEXT
            );
            """
            cur.execute(create_table_query)

            # Insert data
            insert_query = f"""
            INSERT INTO {table_name} (
                timestamp, expiry, strike_price, underlying_spot_price,
                call_ltp, call_close_price, call_volume, call_oi,
                call_bid_price, call_bid_qty, call_ask_price, call_ask_qty,
                call_vega, call_theta, call_gamma, call_delta, call_iv,
                put_ltp, put_close_price, put_volume, put_oi,
                put_bid_price, put_bid_qty, put_ask_price, put_ask_qty,
                put_vega, put_theta, put_gamma, put_delta, put_iv,
                pcr, underlying_key
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s
            );
            """
            
            values = (
                datetime.now(),
                data.get('expiry'),
                data.get('strike_price'),
                data.get('underlying_spot_price'),
                data['call_options']['market_data'].get('ltp'),
                data['call_options']['market_data'].get('close_price'),
                data['call_options']['market_data'].get('volume'),
                data['call_options']['market_data'].get('oi'),
                data['call_options']['market_data'].get('bid_price'),
                data['call_options']['market_data'].get('bid_qty'),
                data['call_options']['market_data'].get('ask_price'),
                data['call_options']['market_data'].get('ask_qty'),
                data['call_options']['option_greeks'].get('vega'),
                data['call_options']['option_greeks'].get('theta'),
                data['call_options']['option_greeks'].get('gamma'),
                data['call_options']['option_greeks'].get('delta'),
                data['call_options']['option_greeks'].get('iv'),
                data['put_options']['market_data'].get('ltp'),
                data['put_options']['market_data'].get('close_price'),
                data['put_options']['market_data'].get('volume'),
                data['put_options']['market_data'].get('oi'),
                data['put_options']['market_data'].get('bid_price'),
                data['put_options']['market_data'].get('bid_qty'),
                data['put_options']['market_data'].get('ask_price'),
                data['put_options']['market_data'].get('ask_qty'),
                data['put_options']['option_greeks'].get('vega'),
                data['put_options']['option_greeks'].get('theta'),
                data['put_options']['option_greeks'].get('gamma'),
                data['put_options']['option_greeks'].get('delta'),
                data['put_options']['option_greeks'].get('iv'),
                data.get('pcr'),
                data.get('underlying_key')
            )

            cur.execute(insert_query, values)
            conn.commit()

        except Exception as e:
            logging.error(f"Error inserting data: {e}")
        finally:
            if conn:
                conn.close()

class OptionChainFetcher:

    def __init__(self, db_manager):
        self.expiry_manager = ExpiryDateManager()
        self.db_manager = db_manager
        
    def sanitize_table_name(self, expiry_date, instrument_key):
        """Convert expiry date and instrument key into valid table name"""
        sanitized_instrument_key = instrument_key.replace(' ', '_').replace('|', '_').lower()
        sanitized_expiry_date = expiry_date.replace('-', '_')
        return f"{sanitized_instrument_key}_{sanitized_expiry_date}"

    def fetch_data(self):
        """Fetch option chain data using current expiries"""
        current_dir = Path(__file__).parent
        token_path = current_dir / 'api' / 'token' / 'accessToken_order.txt'
        
        try:
            with open(token_path, 'r') as file:
                access_token = file.read().strip()
        except FileNotFoundError:
            console.print("[bold red]Error:[/] Access token file not found")
            return
        
        # Update expiries if needed (once per day)
        expiry_dates = self.expiry_manager.update_expiries()
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn()
        ) as progress:
            fetch_task = progress.add_task(
                "[cyan]Fetching option chain data...", 
                total=len(expiry_dates)
            )
            
            for expiry_date in expiry_dates:
                try:
                    params = {
                        'instrument_key': 'NSE_INDEX|Nifty 50',
                        'expiry_date': expiry_date
                    }
                    headers = {
                        'Accept': 'application/json',
                        'Authorization': f'Bearer {access_token}'
                    }
                    
                    response = requests.get(
                        'https://api.upstox.com/v2/option/chain',
                        params=params,
                        headers=headers
                    )
                    response.raise_for_status()
                    data = response.json()
                    
                    if data.get('status') == 'success':
                        self.process_data(data.get('data', []), expiry_date)
                        
                except Exception as e:
                    console.print(f"[bold red]Error fetching data for {expiry_date}:[/] {str(e)}")
                
                progress.update(fetch_task, advance=1)
                t.sleep(0.5)  # Rate limiting

    def process_data(self, data_items, expiry_date):
        """Process and insert data"""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console
        ) as progress:
            insert_task = progress.add_task(
                f"[green]Processing {expiry_date.strftime('%Y-%m-%d')}...",
                total=len(data_items)
            )
            
            for item in data_items:
                table_name = self.sanitize_table_name(
                    str(item.get('expiry')),
                    item.get('underlying_key', 'unknown')
                )
                self.db_manager.insert_data(table_name, item)
                progress.update(insert_task, advance=1)

    def sanitize_table_name(self, expiry_date, instrument_key):
        """Convert expiry date and instrument key into valid table name"""
        sanitized_instrument_key = instrument_key.replace(' ', '_').replace('|', '_').lower()
        sanitized_expiry_date = expiry_date.replace('-', '_')
        return f"{sanitized_instrument_key}_{sanitized_expiry_date}"

def is_market_open():
    """Check if market is currently open"""
    now = datetime.now(pytz.timezone('Asia/Kolkata'))
    current_time = now.time()
    return dt_time(9, 14) <= current_time <= dt_time(19, 30)

def main():
    console.print(Panel.fit(
        "[bold cyan]Option Chain Data Service[/]\n"
        "[green]Press Ctrl+C to exit[/]",
        border_style="blue"
    ))
    
    try:
        db_manager = DatabaseManager()
        fetcher = OptionChainFetcher(db_manager)
        
        def fetch_and_insert():
            if is_market_open():
                console.print("\n[bold green]Market is open. Starting data fetch...[/]")
                fetcher.fetch_data()
            else:
                console.print("\n[yellow]Market is closed.[/]")
        
        # Schedule tasks
        schedule.every(1).seconds.do(fetch_and_insert)
        
        while True:
            schedule.run_pending()
            t.sleep(1)
            
    except KeyboardInterrupt:
        console.print("\n[bold red]Service stopped by user[/]")
    except Exception as e:
        console.print(f"\n[bold red]Error:[/] {str(e)}")

if __name__ == "__main__":
    main()
