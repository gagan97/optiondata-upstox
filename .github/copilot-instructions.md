# Copilot Instructions for Upstox Option Data Trading System

## Project Overview
This is an **archived reference codebase** for a trading system that collects real-time option chain data from Upstox API, stores it in PostgreSQL, and provides Dash-based dashboards for analysis. The system focuses on Indian market indices (Nifty, Bank Nifty, Sensex, etc.) and uses automated trading workflows.

## Key Architecture Components

### Authentication & Token Management
- **Multi-API approach**: Three separate API keys (`apikey_his`, `apikey_order`, `apikey_oc`) for different functions
- **Token persistence**: Access tokens stored in `api/token/accessToken_*.txt` files
- **TOTP integration**: Uses `pyotp` for 2FA with hardcoded secret in `api.py`
- **Selenium automation**: `loginCLI.py` automates browser-based login flow

### Data Pipeline Architecture
```
Upstox API → Real-time collectors → PostgreSQL → Dash dashboards
```

### Database Structure
- **AWS RDS PostgreSQL**: Connection configs in `api/ini/*.ini` files
- **Table naming**: Uses instrument keys as table names (e.g., `NSE_INDEX|Nifty 50`)
- **Schema**: Real-time OHLC + option chain data with millisecond timestamps
- **Auto-creation**: `configDB.py` handles database and table creation

## Critical File Patterns

### Historical Data Collectors
- `historic_optionChain_*.py` - Real-time option chain data for specific indices
- `historic_*.py` - Historical data fetchers for different segments (NSE, BSE, MCX)
- All use `schedule` library for periodic execution (typically 1-second intervals)

### Instrument Management
- Instrument data downloaded from Upstox as gzipped JSON files
- Stored in `api/instrument/` directory
- Key format: `{EXCHANGE}_{SEGMENT}|{SYMBOL}` (e.g., `NSE_INDEX|Nifty 50`)

### Automation System
- `autorun.py` - Master orchestrator that manages login/logout cycles
- Runs only during market hours (9:00-15:30) on weekdays
- Uses multiprocessing to run multiple data collectors simultaneously

## Development Conventions

### Configuration Management
- **INI files**: Database configs in `api/ini/{segment}.ini`
- **Credentials**: Hardcoded in `api.py` (API keys, mobile, PIN, TPIN)
- **Paths**: Relative paths from project root (`api/logs/`, `api/token/`, etc.)

### Logging Strategy
- **Rotating logs**: `RotatingFileHandler` with 5MB max, 5 backups
- **Structured naming**: `{component}_{index}.log` (e.g., `OC_BankNifty.log`)
- **Debug mode**: Configurable via `DEBUG_MODE` flag in scripts

### Error Handling Patterns
- Database connection retries with exponential backoff
- API rate limiting handled with sleep intervals
- Graceful degradation during market holidays

### Market-Specific Logic
- **Trading hours**: 9:00-15:30 IST hardcoded across components  
- **Weekday checks**: `datetime.now().weekday() < 5`
- **Index mapping**: Specific instrument keys for each major index

## Key Dependencies
- **upstox_client**: Official Upstox Python SDK
- **selenium**: Browser automation for login
- **psycopg2**: PostgreSQL connectivity
- **dash**: Web dashboards with Plotly charts
- **protobuf**: WebSocket data parsing (`MarketDataFeed_pb2.py`)

## Debugging Workflows

### Authentication Issues
1. Check token files in `api/token/`
2. Verify TOTP secret in `api.py`
3. Run `loginCLI.py` manually to regenerate tokens

### Data Collection Problems
1. Check logs in `api/logs/` for specific collector
2. Verify database connectivity with `configDB.py`
3. Validate instrument keys against downloaded JSON files

### Database Issues
1. Connection configs in `api/ini/*.ini` files
2. Use `db.py` for manual database operations
3. Check AWS RDS connectivity and credentials

## Important Notes
- **Archive status**: This is reference code - not for production use
- **Hardcoded credentials**: All sensitive data is embedded in `api.py`
- **Market timing**: Indian market hours (IST) hardcoded throughout
- **Single-threaded collectors**: Each option chain script handles one index
- **No containerization**: Direct Python execution expected

When modifying this codebase, preserve the existing file structure and naming conventions, especially the `api/` directory organization and instrument key formats.