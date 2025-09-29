# Copilot Instructions

## Project snapshot
- Collects Upstox option-chain data for multiple Indian indices and persists it to Postgres.
- Root `autorun.py` orchestrates daily login/logout and kicks off each `historic_optionChain/OC_*.py` worker during trading hours.

## Core modules & flow
- `historic_optionChain/loginCLI.py` automates Upstox authentication (headless Chrome at `/snap/bin/chromium.chromedriver`), writes tokens under `historic_optionChain/api/token/*.txt`, and prints account diagnostics via `upstox_client`.
- `historic_optionChain/logoutCLI.py` revokes tokens in bulk; expect it to delete the `.txt` files so `loginCLI` must be run before market open.
- Each `historic_optionChain/OC_<INDEX>.py` has the same scaffold: `MarketCalendar` gates execution using the Upstox holiday API, `ExpiryManager` resolves the next expiries (weekday differs per index), and `DataFetcher` threads pull `https://api.upstox.com/v2/option/chain` while the market is open and push rows into Postgres via `psycopg2`.
- All fetchers read the access token from `historic_optionChain/api/token/accessToken_oc.txt` and DB credentials from environment variables loaded via `historic_optionChain/db_settings.py`; they log to rotating files in `historic_optionChain/api/logs/`.

## Development conventions
- Prefer `Path(__file__).parent` for file lookups; new scripts should mirror the constants at the top of `OC_Bankex.py` so logs/configs resolve relative to the module.
- Table names are derived with `sanitize_table_name(expiry_date, instrument_key)`; keep instrument keys formatted like `BSE_INDEX|BANKEX` to avoid collision.
- Concurrency is thread-based per expiry; always guard shared `progress_data` with the provided `threading.Lock`.
- Handle network retries conservatively—existing code sleeps one second between polls and records errors in the progress table instead of raising.

## Running & debugging
- To refresh credentials: `python historic_optionChain/loginCLI.py` (ensure `totp_secret`, PIN, and chromedriver path are valid for your environment).
- Daily automation: `python autorun.py --mode schedule` (weekday 09:00 IST window) or `--mode schedule-always` to bypass trading-hour checks.
- Individual fetcher dry-run: execute the relevant `OC_*.py` directly after placing a valid token file; check logs in `historic_optionChain/api/logs/<INDEX>.log`.
- Postgres targets must exist; workers call `check_and_create_db` once and expect valid `POSTGRES_*` variables in `.env`. Keep secrets in `.env` (ignored by git) rather than committing them.
- Quick token health-check: run `python autorun.py --mode loginCLI-logoutCLI` to cycle tokens once without launching the long-running fetchers.
- For sandbox/testing, `historic_optionChain/test.py` reuses the same pipeline and reads from the shared `.env`; override values by exporting different `POSTGRES_*` variables before launching if needed.

## Data model hints
- `insert_data_into_db` creates tables per expiry/instrument with a fixed schema (LTP, Greeks, bid/ask book, PCR). Reuse that helper so analytics jobs see a consistent column layout.
- Indexes on `underlying_key`, `strike_price`, and `expiry` are created on first write—avoid custom DDL unless you also maintain those indexes.

## Supporting utilities
- `db-migration-v1.py` copies tables between the OptionChain capture DB and a downstream OptionData DB using Rich progress bars; confirm source/target DSNs in `api/ini/test.ini` and `optiondata.ini` before running.
- `git-updateV1.py` provides a Rich dashboard to add/commit/push repo changes programmatically; it assumes the `main` branch remote is configured.

## Extending the system
- When onboarding a new index, duplicate an `OC_*.py`, update `LOG_FILE`, `instrument_key`, and the expiry cadence inside `ExpiryManager` (weekday logic), and reuse the shared helpers.
- Keep secrets out of version control; migrate values from `historic_optionChain/api/api.py` into environment variables or `.ini` files prior to publishing changes.

## Gotchas
- Selenium requires a Chrome/Chromium binary accessible to the headless driver; adjust `perform_login_process` if your platform path differs.
- Upstox APIs throttle aggressively—avoid tightening the `t.sleep(1)` loops and log response payloads when debugging rather than printing to stdout (logs are already routed to both file and console).
- Market calendar checks depend on live HTTP calls; fall back handlers (`market_holiday_date_wise_safe`) already default to empty lists—respect that pattern when adding new checks.
