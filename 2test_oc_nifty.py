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
import calendar
from rich.console import Console
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text
from rich import box
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import threading


# Call the function
market_holiday_date_wise()

# Function to ensure paths are correctly located in executable
def resource_path(relative_path):
    """Get the absolute path to the resource, works for dev and for PyInstaller."""
    try:
        # PyInstaller creates a temp folder and stores the path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# Ensure the directory exists
log_directory = "api/logs"
if not os.path.exists(log_directory):
    os.makedirs(log_directory)

# Configure logging with rotating file handler
log_file = "api/logs/test.log"
handler = RotatingFileHandler(log_file, maxBytes=5000000, backupCount=5)  # 5 MB max per log file, keep 5>
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

# Root logger
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
logger.addHandler(handler)

logger.info("Starting real-time data insertion script.")

# Function to get the last Thursday of a given month
# def get_last_thursday(year, month):
#     last_day = datetime(year, month, 1) + timedelta(days=31)
#     last_day -= timedelta(days=last_day.day)
#     last_thursday = last_day - timedelta(days=(last_day.weekday() - 3) % 7)

#     india_holidays = holidays.India(years=year)
#     if last_thursday.weekday() > 4 or last_thursday in india_holidays:
#         logging.info(f"{last_thursday.date()} is a weekend or holiday.")
#         last_thursday -= timedelta(days=1)

#     logging.info(f"Last Thursday expiry date is {last_thursday.date()}.")
#     return last_thursday.date()

def print_expiry_info(expiry_dates):
    """Print formatted expiry dates information to terminal"""
    print(f"\n{Fore.CYAN}{'='*50}")
    print(f"{Fore.GREEN}NIFTY50 OPTION CHAIN EXPIRY DATES")
    print(f"{Fore.CYAN}{'='*50}{Style.RESET_ALL}")

    now = datetime.now().date()

    for i, date in enumerate(expiry_dates, 1):
        if date == now:
            print(f"{Fore.YELLOW}Expiry {i}: {date} (TODAY){Style.RESET_ALL}")
        elif date < now:
            print(f"{Fore.RED}Expiry {i}: {date} (PAST){Style.RESET_ALL}")
        else:
            print(f"{Fore.GREEN}Expiry {i}: {date} (UPCOMING){Style.RESET_ALL}")

    print(f"{Fore.CYAN}{'='*50}{Style.RESET_ALL}\n")


def get_all_thursday_expiries(year, month):
    """Get all Thursday expiry dates for a given month."""
    logging.info(f"Getting all Thursday expiries for {year}-{month}")

    # Get the holiday response once for the month
    holiday_response = market_holiday_date_wise()
    holidays_list = []

    if holiday_response and holiday_response.get('status') == 'success' and holiday_response.get('data'):
        holidays_list = [holiday['date'] for holiday in holiday_response['data']]

    # Get all dates for the month
    c = calendar.monthcalendar(year, month)

    # Thursday is represented by 3 in calendar
    thursday_dates = []

    for week in c:
        thursday = week[3]
        if thursday != 0:  # 0 means the day belongs to another month
            thursday_date = datetime(year, month, thursday).date()

            # Check if Thursday is a holiday
            if thursday_date.strftime('%Y-%m-%d') in holidays_list:
                # Get previous trading day
                temp_date = thursday_date
                while temp_date.strftime('%Y-%m-%d') in holidays_list or temp_date.weekday() > 4:
                    temp_date -= timedelta(days=1)
                thursday_dates.append(temp_date)
                print(f"{Fore.YELLOW}Holiday found on {thursday_date}, adjusted to {temp_date}{Style.RESET_ALL}")
            else:
                thursday_dates.append(thursday_date)

    # Print expiry dates to terminal
    print_expiry_info(thursday_dates)
    logging.info(f"Found expiry dates: {thursday_dates}")
    return thursday_dates

def get_next_thursday(year, month, today=None):
    if today is None:
        today = datetime.today()

    # Call the market_holiday_date_wise function and process its response
    holiday_response = market_holiday_date_wise()

    holidays_list = []

    # Ensure holiday_response is not None before accessing its contents
    if holiday_response is None:
        logging.error("Error: Holiday response is None. Skipping holiday check.")
    elif holiday_response.get('status') == 'success' and holiday_response.get('data'):
        # If there are holidays, extract them
        holidays_list = [(holiday['date'], holiday['description']) for holiday in holiday_response['data']]
        for holiday in holidays_list:
            logging.info(f"Holiday on {holiday[0]}: {holiday[1]}")
    else:
        logging.warning("Holiday response status is not 'success' or no data returned.")

    # Check if today is a weekend
    if today.weekday() == 5:  # Saturday
        logging.info("Today is a weekend holiday (Saturday).")
    elif today.weekday() == 6:  # Sunday
        logging.info("Today is a weekend holiday (Sunday).")
    else:  # Weekday (Monday to Friday)
        # Check if today is a holiday
        if today.date().strftime('%Y-%m-%d') in [h[0] for h in holidays_list]:
            logging.info(f"{today.date()} is a holiday. Adjusting the date.")
            today += timedelta(days=1)  # Move to the next day if today is a holiday

    # Calculate the days until the next Thursday
    days_ahead = (3 - today.weekday() + 7) % 7  # 3 represents Thursday
    if days_ahead == 0:  # If today is Thursday, move to next week
        days_ahead = 7

    next_thursday = today + timedelta(days=days_ahead)

    india_holidays = holidays.India(years=year)

    # If the next Thursday is a holiday or a weekend, get the previous trading day
    while next_thursday.weekday() > 4 or next_thursday in india_holidays:
        logging.info(f"{next_thursday.date()} is a weekend or holiday. Finding the previous trading day.")
        next_thursday -= timedelta(days=1)

    next_thursday_date = next_thursday.date()  # Extract the final date
    logging.info(f"Next Thursday expiry date is {next_thursday_date}.")

    return next_thursday_date


def get_current_timestamp():
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S") + f".{now.microsecond // 1000:03d}"

# Fetch database config
def configDB(filename="api/ini/test.ini", section="postgresql"):
    parser = ConfigParser()
    parser.read(filename)
    db = {}
    if parser.has_section(section):
        params = parser.items(section)
        for param in params:
            db[param[0]] = param[1]
    else:
        logging.error(f"Section {section} not found in {filename} file.")
        raise Exception(f'Section {section} not found in {filename} file.')
    return db

# Check and create database if not exists
def check_and_create_db(db_config):
    logging.debug("Checking if the database exists.")
    conn = None
    try:
        conn = psycopg2.connect(
            host=db_config['host'],
            user=db_config['user'],
            password=db_config['password'],
            port=db_config.get('port', 5432),
            database='postgres'
        )
        logging.info("Database connected successfully.")
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(sql.SQL("SELECT 1 FROM pg_database WHERE datname = %s"), [db_config['database']])
        exists = cur.fetchone()
        if not exists:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_config['database'])))
            logging.info(f"Database {db_config['database']} created successfully.")
        else:
            logging.info(f"Database {db_config['database']} already exists.")
        cur.close()
    except Exception as e:
        logging.error(f"Error checking or creating database: {e}")
    finally:
        if conn is not None:
            conn.close()

# Helper function to sanitize table names
def sanitize_table_name(expiry_date, instrument_key):
    logging.debug(f"Expiry Date is {expiry_date}.")
    sanitized_instrument_key = instrument_key.replace(' ', '_').replace('|', '_').lower()
    sanitized_expiry_date = expiry_date.replace('-', '_')
    return f"{sanitized_instrument_key}_{sanitized_expiry_date}"

# Database insertion function
def insert_data_into_db(db_config, table_name, data):
    logging.debug(f"Inserting data into table {table_name}.")
    conn = None
    try:
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()

        # Create the table if it doesn't exist
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
        logging.info("Table created or verified successfully.")

        # Insert data
        insert_query = f"""
        INSERT INTO {table_name} (timestamp, expiry, strike_price, underlying_spot_price, call_ltp, call_>
                                  call_bid_price, call_bid_qty, call_ask_price, call_ask_qty, call_vega, >
                                  put_ltp, put_close_price, put_volume, put_oi, put_bid_price, put_bid_qt>
                                  put_vega, put_theta, put_gamma, put_delta, put_iv, pcr, underlying_key)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %>
        """

        # Extract values
        values = (
            get_current_timestamp(),
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

        
        # Create indexes
        cur.execute(sql.SQL("""
            CREATE INDEX IF NOT EXISTS {}
            ON {} (underlying_key)
        """).format(
            sql.Identifier(f"idx_{table_name}_underlying_key"),
            sql.Identifier(table_name)
        ))
        cur.execute(sql.SQL("""
            CREATE INDEX IF NOT EXISTS {}
            ON {} (strike_price)
        """).format(
            sql.Identifier(f"idx_{table_name}_strike_price"),
            sql.Identifier(table_name)
        ))
        cur.execute(sql.SQL("""
            CREATE INDEX IF NOT EXISTS {}
            ON {} (expiry)
        """).format(
            sql.Identifier(f"idx_{table_name}_expiry"),
            sql.Identifier(table_name)
        ))

        # Log SQL query and values
        logging.debug(f"SQL Query: {insert_query}")
        logging.debug(f"Values: {values}")

        # Execute insertion
        cur.execute(insert_query, values)

        conn.commit()
        logging.info("Data inserted successfully.")
        cur.close()

    except Exception as error:
        logging.error(f"Error while inserting data into {table_name}: {error}")
    finally:
        if conn is not None:
            conn.close()

@lru_cache(maxsize=1)
def check_market_status():
    """
    Check market status once and cache the result
    Returns: tuple (is_open: bool, message: str)
    """
    try:
        # Get current time in IST
        now = datetime.now(pytz.timezone('Asia/Kolkata'))
        current_date = now.strftime('%Y-%m-%d')

        # Check holiday status
        holiday_response = market_holiday_date_wise()

        if holiday_response and holiday_response.get('status') == 'success':
            holidays_list = [holiday['date'] for holiday in holiday_response.get('data', [])]

            if current_date in holidays_list:
                return False, f"Market is closed (Holiday: {current_date})"

            # Check market hours (9:15 AMhours (9:15 AM to 3:30 PM IST)
            market_start = now.replace(hour=9, minute=15, second=0, microsecond=0)
            market_end = now.replace(hour=15, minute=30, second=0, microsecond=0)

            if market_start <= now <= market_end and now.weekday() < 5:
                return True, "Market is open"
            else:
                return False, "Market is closed (Outside trading hours)"
        else:
            return False, "Could not verify market status"

    except Exception as e:
        logging.error(f"Error checking market status: {e}")
        return False, f"Error checking market status: {e}"


class DashboardUI:
    def __init__(self):
        self.console = Console()
        self.layout = Layout()
        self.last_update = datetime.now()
        self.market_status = "Checking..."
        self.current_operations = []
        self.error_messages = []
        self.success_count = 0
        self.error_count = 0
        self.setup_layout()
        
    def setup_layout(self):
        """Setup the layout structure"""
        self.layout.split(
            Layout(name="header", size=3),
            Layout(name="main", size=15),
            Layout(name="footer", size=7)
        )
        
        # Split main area into left and right
        self.layout["main"].split_row(
            Layout(name="left"),
            Layout(name="right")
        )
        
        # Split footer into sections
        self.layout["footer"].split_row(
            Layout(name="operations", minimum_size=50),
            Layout(name="errors")
        )

    def generate_header(self):
        """Generate the header section"""
        grid = Table.grid(expand=True)
        grid.add_column(justify="center", ratio=1)
        grid.add_row("[bold yellow]NIFTY OPTIONS CHAIN DATA FETCHER[/]")
        grid.add_row(f"Last Update: {self.last_update.strftime('%Y-%m-%d %H:%M:%S')}")
        return Panel(grid, style="bold white")

    def generate_status_panel(self):
        """Generate the status panel"""
        status_color = "green" if self.market_status == "Market is open" else "red"
        status_table = Table(box=box.ROUNDED, expand=True)
        status_table.add_column("Metric", justify="right", style="cyan")
        status_table.add_column("Value", justify="left")
        status_table.add_row("Market Status", f"[{status_color}]{self.market_status}[/]")
        status_table.add_row("Successful Fetches", f"[green]{self.success_count}[/]")
        status_table.add_row("Failed Fetches", f"[red]{self.error_count}[/]")
        return Panel(status_table, title="System Status", border_style="blue")

    def generate_operations_panel(self):
        """Generate the operations panel"""
        ops_table = Table(box=box.ROUNDED, expand=True)
        ops_table.add_column("Time", style="cyan")
        ops_table.add_column("Operation", style="white")
        ops_table.add_column("Status", justify="right")
        
        # Show last 5 operations
        for op in self.current_operations[-5:]:
            ops_table.add_row(
                op['time'].strftime('%H:%M:%S'),
                op['message'],
                op['status']
            )
        return Panel(ops_table, title="Recent Operations", border_style="blue")

    def generate_errors_panel(self):
        """Generate the errors panel"""
        error_table = Table(box=box.ROUNDED, expand=True)
        error_table.add_column("Time", style="cyan")
        error_table.add_column("Error", style="red")
        
        # Show last 5 errors
        for error in self.error_messages[-5:]:
            error_table.add_row(
                error['time'].strftime('%H:%M:%S'),
                error['message']
            )
        return Panel(error_table, title="Recent Errors", border_style="red")

    def update(self):
        """Update the dashboard layout"""
        self.layout["header"].update(self.generate_header())
        self.layout["left"].update(self.generate_status_panel())
        self.layout["operations"].update(self.generate_operations_panel())
        self.layout["errors"].update(self.generate_errors_panel())

    def add_operation(self, message, status="[yellow]RUNNING[/]"):
        """Add a new operation to the list"""
        self.current_operations.append({
            'time': datetime.now(),
            'message': message,
            'status': status
        })
        if len(self.current_operations) > 20:  # Keep only last 20 operations
            self.current_operations.pop(0)

    def add_error(self, message):
        """Add a new error to the list"""
        self.error_messages.append({
            'time': datetime.now(),
            'message': message
        })
        if len(self.error_messages) > 20:  # Keep only last 20 errors
            self.error_messages.pop(0)
        self.error_count += 1

    def mark_success(self):
        """Increment success counter"""
        self.success_count += 1

class ModernOptionChainFetcher:
    def __init__(self):
        self.dashboard = DashboardUI()
        self.max_retries = 3
        self.retry_delay = 5

    def fetch_with_retry(self, url, params, headers):
        """Fetch data with retry logic"""
        for attempt in range(self.max_retries):
            try:
                self.dashboard.add_operation(f"Attempting API call ({attempt + 1}/{self.max_retries})")
                response = requests.get(url, params=params, headers=headers, timeout=30)
                response.raise_for_status()
                self.dashboard.add_operation(
                    f"API call successful",
                    status="[green]SUCCESS[/]"
                )
                return response.json()
            except requests.exceptions.RequestException as e:
                if attempt == self.max_retries - 1:
                    self.dashboard.add_error(f"API call failed: {str(e)}")
                    raise
                self.dashboard.add_operation(
                    f"API call failed, retrying...",
                    status="[yellow]RETRY[/]"
                )
                t.sleep(self.retry_delay)
        return None

    def process_single_expiry(self, expiry_date, access_token):
        """Process a single expiry date"""
        try:
            self.dashboard.add_operation(f"Processing expiry date: {expiry_date}")
            
            params = {
                'instrument_key': 'NSE_INDEX|Nifty 50',
                'expiry_date': expiry_date
            }
            headers = {
                'Accept': 'application/json',
                'Authorization': f'Bearer {access_token}'
            }
            
            data = self.fetch_with_retry(
                'https://api.upstox.com/v2/option/chain',
                params=params,
                headers=headers
            )
            
            if not data:
                self.dashboard.add_error(f"No data received for {expiry_date}")
                return False
            
            if data.get('status') == 'success' and 'data' in data:
                records = []
                for item in data['data']:
                    if not all(k in item for k in ['expiry', 'strike_price', 'underlying_spot_price']):
                        self.dashboard.add_error(f"Incomplete record found for {expiry_date}")
                        continue
                        
                    record = {
                        'expiry': item.get('expiry'),
                        'strike_price': item.get('strike_price'),
                        'underlying_spot_price': item.get('underlying_spot_price'),
                        'pcr': item.get('pcr'),
                        'underlying_key': item.get('underlying_key'),
                        'call_options': item.get('call_options', {}),
                        'put_options': item.get('put_options', {})
                    }
                    records.append(record)
                
                if not records:
                    self.dashboard.add_error(f"No valid records for {expiry_date}")
                    return False
                
                for record in records:
                    table_name = sanitize_table_name(record['expiry'], record['underlying_key'])
                    insert_data_into_db(db_config, table_name, record)
                
                self.dashboard.add_operation(
                    f"Completed processing {expiry_date}",
                    status="[green]SUCCESS[/]"
                )
                self.dashboard.mark_success()
                return True
            else:
                error_msg = data.get('message', 'Unknown error')
                self.dashboard.add_error(f"Failed to process {expiry_date}: {error_msg}")
                return False
                
        except Exception as e:
            self.dashboard.add_error(f"Error processing {expiry_date}: {str(e)}")
            return False

    def start_fetching(self):
        """Main method to start fetching data"""
        with Live(self.dashboard.layout, refresh_per_second=4, screen=True):
            try:
                # Check market status
                is_open, status_message = check_market_status()
                self.dashboard.market_status = status_message
                
                if not is_open and datetime.now().weekday() >= 5:
                    self.dashboard.add_operation(
                        "Weekend - no data collection needed",
                        status="[yellow]SKIPPED[/]"
                    )
                    return
                
                # Find access token
                possible_paths = [
                    Path('api/token/accessToken_order.txt'),
                    Path(__file__).parent / 'api' / 'token' / 'accessToken_order.txt',
                    Path.home() / 'api' / 'token' / 'accessToken_order.txt'
                ]
                
                token_path = None
                for path in possible_paths:
                    if path.exists():
                        token_path = path
                        break
                        
                if not token_path:
                    self.dashboard.add_error("Access token file not found")
                    return
                    
                with open(token_path, 'r') as file:
                    access_token = file.read().strip()
                    
                if not access_token:
                    self.dashboard.add_error("Access token is empty")
                    return
                
                # Get expiry dates
                now = datetime.now()
                current_month_expiries = get_all_thursday_expiries(now.year, now.month)
                next_month = now.replace(day=1) + timedelta(days=32)
                next_month_expiries = get_all_thursday_expiries(next_month.year, next_month.month)
                all_expiries = current_month_expiries + next_month_expiries
                
                # Process expiries
                with ThreadPoolExecutor(max_workers=3) as executor:
                    futures = []
                    for expiry in all_expiries:
                        future = executor.submit(
                            self.process_single_expiry,
                            expiry,
                            access_token
                        )
                        futures.append(future)
                    
                    for future in as_completed(futures):
                        try:
                            future.result()
                        except Exception as e:
                            self.dashboard.add_error(f"Task failed: {str(e)}")
                            
            except Exception as e:
                self.dashboard.add_error(f"Fatal error: {str(e)}")
            
            finally:
                # Add final status
                self.dashboard.add_operation(
                    "Data collection completed",
                    status="[blue]FINISHED[/]"
                )


def fetch_and_insert_data():
    if is_market_open():
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"\n{Fore.CYAN}[{current_time}] Market is open. Fetching data for all expiries.{Style.RESET_ALL}")
        fetcher.start_fetching()
    else:
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"\n{Fore.YELLOW}[{current_time}] Market is closed.{Style.RESET_ALL}")

def convert_milliseconds_to_time(milliseconds):
    """Convert milliseconds timestamp to datetime object in IST."""
    try:
        seconds = milliseconds / 1000
        dt = datetime.fromtimestamp(seconds, pytz.timezone('Asia/Kolkata'))
        logging.info(f"Converted milliseconds {milliseconds} to datetime: {dt}")
        return dt
    except Exception as e:
        logging.error(f"Error converting milliseconds {milliseconds}: {e}")
        return None

def parse_exchange_timings(holiday_data):
    """Parse exchange timings from holiday data."""
    try:
        for exchange_info in holiday_data.get('open_exchanges', []):
            if isinstance(exchange_info, str):
                # Parse the string format "NSE (Start: 1735703100000, End: 1735725600000)"
                parts = exchange_info.split('(')
                exchange_name = parts[0].strip()
                if exchange_name == 'NSE':
                    timing_parts = parts[1].strip(')').split(',')
                    start_ms = int(timing_parts[0].split(':')[1].strip())
                    end_ms = int(timing_parts[1].split(':')[1].strip())
                    return {
                        'name': 'NSE',
                        'start': start_ms,
                        'end': end_ms
                    }
    except Exception as e:
        logging.error(f"Error parsing exchange timings: {e}")
    return None

def is_market_open():
    """Check if market is open based on time, day and holidays"""
    now = datetime.now(pytz.timezone('Asia/Kolkata'))
    current_date = now.strftime('%Y-%m-%d')
    current_day = now.strftime('%A')

    # Weekend check
    if current_day in ['Saturday', 'Sunday']:
        return False, "Weekend Holiday"

    # Check holiday data
    holiday_response = market_holiday_date_wise()
    if holiday_response and holiday_response.get('status') == 'success':
        holidays = holiday_response.get('data', [])
        for holiday in holidays:
            if holiday['date'] == current_date:
                # Parse exchange timings
                exchange_info = parse_exchange_timings(holiday)
                if exchange_info:
                    start_time = convert_milliseconds_to_time(exchange_info['start'])
                    end_time = convert_milliseconds_to_time(exchange_info['end'])
                    if start_time and end_time:
                        is_open = start_time <= now <= end_time
                        return is_open, f"Holiday ({holiday.get('description', 'Special Timing')})"
                return False, f"Holiday ({holiday.get('description', 'Market Closed')})"

    # Regular market hours check (9:00 AM to 3:30 PM)
    market_time = now.time()
    is_regular_open = dt_time(9, 0) <= market_time <= dt_time(15, 30)
    return is_regular_open, "Regular Hours"

def create_status_line():
    """Create a single status line with all information"""
    now = datetime.now(pytz.timezone('Asia/Kolkata'))
    current_day = now.strftime('%A')
    current_datetime = now.strftime('%Y-%m-%d %H:%M:%S')

    market_open, status_reason = is_market_open()

    # Create status text
    status = Text()

    # Base status
    status.append("Status: ", style="cyan")
    status.append("success ", style="green")

    # Holiday/Regular Day status
    if "Holiday" in status_reason:
        status.append(f"{status_reason} ", style="yellow")
    else:
        status.append("No holiday ", style="green")

    # Current date/time and day
    status.append(f"{current_datetime} {current_day} ", style="blue")

    # Market status
    status.append("market ", style="cyan")
    status.append("OPEN" if market_open else "CLOSED",
                 style="green" if market_open else "red")

    return status

if __name__ == "__main__":
    # Initialize database
    db_config = configDB()
    check_and_create_db(db_config)
    
    # Start the fetcher with modern UI
    fetcher = ModernOptionChainFetcher()
    fetcher.start_fetching()

    # Schedule data fetching during market hours every second
    schedule.every(1).seconds.do(fetch_and_insert_data)

    Console.clear()
    console.print("[bold cyan]NIFTY50 OPTION CHAIN MONITOR[/bold cyan]")
    console.print("[green]Service started successfully. Press Ctrl+C to stop.[/green]")

    with Live(create_status_line(), refresh_per_second=1, transient=True) as live:
        while True:
            try:
                live.update(create_status_line())
            except KeyboardInterrupt:
                console.print("\n[yellow]Service stopped[/yellow]")
                sys.exit(0)
