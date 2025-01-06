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
from colorama import init, Fore, Style

# Initialize colorama for colored terminal output
init()

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
log_file = "api/logs/OC_Nifty50.log"
handler = RotatingFileHandler(log_file, maxBytes=5000000, backupCount=5)  # 5 MB max per log file, keep 5 backups
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
def configDB(filename="api/ini/OptionChain.ini", section="postgresql"):
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
        INSERT INTO {table_name} (timestamp, expiry, strike_price, underlying_spot_price, call_ltp, call_close_price, call_volume, call_oi,
                                  call_bid_price, call_bid_qty, call_ask_price, call_ask_qty, call_vega, call_theta, call_gamma, call_delta, call_iv, 
                                  put_ltp, put_close_price, put_volume, put_oi, put_bid_price, put_bid_qty, put_ask_price, put_ask_qty, 
                                  put_vega, put_theta, put_gamma, put_delta, put_iv, pcr, underlying_key)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
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

# Fetch and process data from API
class OptionChainFetcher:
    def fetch_data(self, expiry_date=None):
        """Modified to accept specific expiry date and show progress"""
        current_dir = Path(__file__).parent
        token_path = current_dir / 'api' / 'token' / 'accessToken_order.txt'
        
        try:
            with open(token_path, 'r') as file:
                access_token = file.read().strip()
        except FileNotFoundError:
            logging.error("Access token file not found.")
            print(f"{Fore.RED}Error: Access token file not found{Style.RESET_ALL}")
            return {}

        # If no expiry_date provided, get all expiries for current month
        now = datetime.now()
        if expiry_date is None:
            expiry_dates = get_all_thursday_expiries(now.year, now.month)
        else:
            expiry_dates = [expiry_date]

        all_data = []
        for expiry in expiry_dates:
            print(f"{Fore.CYAN}Fetching data for expiry: {expiry}{Style.RESET_ALL}")
            params = {
                'instrument_key': 'NSE_INDEX|Nifty 50',
                'expiry_date': expiry
            }
            headers = {
                'Accept': 'application/json',
                'Authorization': f'Bearer {access_token}'
            }

            try:
                response = requests.get('https://api.upstox.com/v2/option/chain', 
                                     params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
                if data.get('status') == 'success':
                    print(f"{Fore.GREEN}Successfully fetched data for {expiry}{Style.RESET_ALL}")
                    all_data.append(data)
                else:
                    print(f"{Fore.RED}Failed to fetch data for {expiry}{Style.RESET_ALL}")
            except requests.RequestException as e:
                error_msg = f"Request failed for expiry {expiry}: {e}"
                logging.error(error_msg)
                print(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")

        return all_data

    def start_fetching(self):
        print(f"\n{Fore.CYAN}Starting data fetching for all expiries...{Style.RESET_ALL}")
        all_data = self.fetch_data()

        for data in all_data:
            if data.get('status') == 'success' and 'data' in data:
                for item in data['data']:
                    expiry = item.get('expiry')
                    underlying_key = item.get('underlying_key')
                    table_name = sanitize_table_name(expiry, underlying_key)
                    
                    print(f"{Fore.GREEN}Inserting data for {expiry} into {table_name}{Style.RESET_ALL}")
                    
                    record = {
                        'expiry': expiry,
                        'strike_price': item.get('strike_price'),
                        'underlying_spot_price': item.get('underlying_spot_price'),
                        'pcr': item.get('pcr'),
                        'underlying_key': underlying_key,
                        'call_options': item.get('call_options'),
                        'put_options': item.get('put_options')
                    }
                    insert_data_into_db(db_config, table_name, record)
            else:
                print(f"{Fore.RED}Error processing data batch{Style.RESET_ALL}")

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
    """
    Check if the market is open based on regular hours and holiday special timings.
    Returns: bool
    """
    # Get current time in IST
    now = datetime.now(pytz.timezone('Asia/Kolkata'))
    current_date = now.strftime('%Y-%m-%d')
    
    logging.info(f"Checking market status for date: {current_date}, time: {now.strftime('%H:%M:%S')}")
    
    # Check holiday data
    holiday_response = market_holiday_date_wise()
    
    if holiday_response and holiday_response.get('status') == 'success':
        holidays = holiday_response.get('data', [])
        
        for holiday in holidays:
            logging.info(f"Checking holiday: {holiday}")
            
            if holiday['date'] == current_date:
                logging.info("Today is a holiday with special timing")
                
                # Parse exchange timings
                exchange_info = parse_exchange_timings(holiday)
                
                if exchange_info:
                    start_time = convert_milliseconds_to_time(exchange_info['start'])
                    end_time = convert_milliseconds_to_time(exchange_info['end'])
                    
                    if start_time and end_time:
                        is_open = start_time <= now <= end_time
                        logging.info(f"Special timing check - Start: {start_time}, End: {end_time}, Current: {now}, Is Open: {is_open}")
                        return is_open
    
    # Regular market hours check
    regular_market_time = now.time()
    is_regular_open = dt_time(9, 00) <= regular_market_time <= dt_time(15, 30)
    logging.info(f"Regular market hours check - Is Open: {is_regular_open}")
    return is_regular_open

if __name__ == '__main__':
    print(f"{Fore.CYAN}{'='*50}")
    print(f"{Fore.GREEN}NIFTY50 OPTION CHAIN DATA FETCHER")
    print(f"{Fore.CYAN}{'='*50}{Style.RESET_ALL}")
    
    # Database setup
    db_config = configDB()
    check_and_create_db(db_config)

    fetcher = OptionChainFetcher()

    # Schedule data fetching during market hours every second
    schedule.every(1).seconds.do(fetch_and_insert_data)

    print(f"{Fore.GREEN}Service started successfully. Press Ctrl+C to stop.{Style.RESET_ALL}")
    
    while True:
        try:
            schedule.run_pending()
            t.sleep(1)
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}Stopping service...{Style.RESET_ALL}")
            sys.exit(0)
        except Exception as e:
            error_msg = f"Error in main loop: {e}"
            logging.error(error_msg)
            print(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
