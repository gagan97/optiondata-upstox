# Optiondata Upstox

## Overview
This project automates Upstox option-chain collection for multiple Indian indices. A single PostgreSQL database drives all workers, managed through a local `.env` file and an optional Dockerized Postgres instance.

## Prerequisites
- Python 3.11+
- Docker (optional but recommended for the bundled Postgres service)
- Chrome/Chromium with a compatible chromedriver for the selenium-based login flow

## Environment configuration
1. Copy `.env.example` to `.env`.
2. Update the values to match your local or remote PostgreSQL credentials.

```bash
cp .env.example .env
```

The same `.env` file feeds:
- Python workers via `historic_optionChain/db_settings.py`
- The Docker Compose Postgres service
- Migration tooling (`db-migration-v1.py`)

## Running the database locally
Launch the Postgres container on the same VM:

```bash
docker compose up -d
```

Data persists in the named Docker volume `postgres_data`. Stop the service with:

```bash
docker compose down
```

## Updating environment variables
If you change `.env`, restart long-running processes (including Docker) so they pick up the new values.

## Worker execution
After ensuring a valid token in `historic_optionChain/api/token/accessToken_oc.txt`, run any worker directly:

```bash
python historic_optionChain/OC_Nifty50.py
```

Or orchestrate the full schedule:

```bash
python autorun.py --mode schedule
```

## Database migrations
`db-migration-v1.py` now uses environment variables. To migrate between two databases, define an additional set of env vars with the `TARGET_POSTGRES_` prefix. If those are absent, the migration falls back to the primary `POSTGRES_` settings.
