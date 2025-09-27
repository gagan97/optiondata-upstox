"""Utility script to fetch portfolio positions and trade P&L data from Upstox.

Usage examples:
    python fetch_portfolio_pnl.py
    python fetch_portfolio_pnl.py --from-date 2024-01-01 --to-date 2024-01-31 --segment EQUITY
    python fetch_portfolio_pnl.py --token-file /path/to/token.txt --output-json upstox_dump.json

This script expects a valid Upstox access token stored in the token directory that the
existing login automation writes to (default: api/token/accessToken_oc.txt).
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

API_BASE_URL = "https://api.upstox.com/v2"
DEFAULT_TOKEN_FILENAME = "accessToken_oc.txt"


def load_access_token(token_path: Path) -> str:
    if not token_path.exists():
        raise FileNotFoundError(
            f"Access token file not found at {token_path}. Run loginCLI.py first or supply --token-file."
        )

    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError(f"Access token file at {token_path} is empty.")
    return token


def api_get(endpoint: str, token: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{API_BASE_URL}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    response = requests.get(url, headers=headers, params=params, timeout=30)
    try:
        payload = response.json()
    except json.JSONDecodeError:
        response.raise_for_status()
        raise RuntimeError(f"Received non-JSON response from {url}") from None

    if response.status_code >= 400 or payload.get("status") == "error":
        message = payload.get("message") or payload.get("errors") or payload
        raise RuntimeError(f"API call to {endpoint} failed: {message}")

    return payload


def format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def render_table(title: str, data: Iterable[Dict[str, Any]], columns: List[str]) -> None:
    if not data:
        print(f"No records returned for {title}")
        return

    print(f"\n{title}")
    header = [column.replace("_", " ").title() for column in columns]
    header_line = " | ".join(header)
    print(header_line)
    print("-" * len(header_line))
    for item in data:
        row = [format_value(item.get(column)) for column in columns]
        print(" | ".join(row))


def ensure_date(value: Optional[str], fallback: date) -> date:
    if not value:
        return fallback
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}'. Expected format YYYY-MM-DD.") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch portfolio and trade P&L data from Upstox.")
    parser.add_argument(
        "--token-file",
        type=Path,
        default=Path(__file__).resolve().parent / "api" / "token" / DEFAULT_TOKEN_FILENAME,
        help="Path to the file containing the Upstox access token.",
    )
    parser.add_argument(
        "--from-date",
        help="Start date for trade P&L data (YYYY-MM-DD). Defaults to 7 days ago.",
    )
    parser.add_argument(
        "--to-date",
        help="End date for trade P&L data (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--segment",
        help="Optional segment filter for trade P&L data (e.g., EQUITY, FNO).",
    )
    parser.add_argument(
        "--product-type",
        help="Optional product type filter for trade P&L data (e.g., DELIVERY, INTRADAY).",
    )
    parser.add_argument(
        "--instrument-type",
        help="Optional instrument type filter for trade P&L data.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        help="If provided, dump the raw API payloads to this JSON file.",
    )
    parser.add_argument(
        "--skip-pnl",
        action="store_true",
        help="Skip calling trade P&L endpoints (only fetch portfolio data).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        token = load_access_token(args.token_file)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    print("\n==== Portfolio Snapshot ====")

    try:
        short_positions = api_get("/portfolio/short-term-positions", token).get("data", [])
        render_table(
            "Short-Term Positions",
            short_positions,
            [
                "trading_symbol",
                "exchange",
                "product",
                "quantity",
                "average_price",
                "pnl",
                "unrealised",
                "realised",
                "last_price",
            ],
        )

        long_holdings = api_get("/portfolio/long-term-holdings", token).get("data", [])
        render_table(
            "Long-Term Holdings",
            long_holdings,
            [
                "trading_symbol",
                "exchange",
                "quantity",
                "average_price",
                "ltp",
                "pnl",
                "investment_value",
                "current_value",
            ],
        )
    except RuntimeError as exc:
        print(f"Failed to fetch portfolio data: {exc}")
        raise SystemExit(1) from exc

    output_payload: Dict[str, Any] = {
        "short_term_positions": short_positions,
        "long_term_holdings": long_holdings,
    }

    if not args.skip_pnl:
        print("\n==== Trade Profit & Loss ====")

        try:
            pnl_metadata = api_get("/trade/profit-loss/metadata", token).get("data", {})
            print("Available profit & loss metadata:")
            print(json.dumps(pnl_metadata, indent=2))
            output_payload["trade_pnl_metadata"] = pnl_metadata
        except RuntimeError as exc:
            print(f"Failed to fetch P&L metadata: {exc}")
            pnl_metadata = {}

        today = date.today()
        default_from = today - timedelta(days=7)
        from_date = ensure_date(args.from_date, default_from)
        to_date = ensure_date(args.to_date, today)

        if from_date > to_date:
            print("from-date cannot be after to-date.")
            raise SystemExit(1)

        pnl_params: Dict[str, Any] = {
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
        }
        if args.segment:
            pnl_params["segment"] = args.segment
        if args.product_type:
            pnl_params["product_type"] = args.product_type
        if args.instrument_type:
            pnl_params["instrument_type"] = args.instrument_type

        message = (
            f"Fetching trade P&L data for {pnl_params['from_date']} to {pnl_params['to_date']}"
        )
        print(message)

        try:
            pnl_data_response = api_get("/trade/profit-loss/data", token, params=pnl_params)
            pnl_data = pnl_data_response.get("data", [])
            output_payload["trade_pnl_params"] = pnl_params
            output_payload["trade_pnl_data"] = pnl_data

            if isinstance(pnl_data, list):
                render_table(
                    "Trade Profit & Loss",
                    pnl_data,
                    [
                        "trade_date",
                        "segment",
                        "trading_symbol",
                        "quantity",
                        "buy_value",
                        "sell_value",
                        "pnl",
                    ],
                )
            else:
                print(json.dumps(pnl_data, indent=2))
        except RuntimeError as exc:
            print(f"Failed to fetch trade P&L data: {exc}")

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(output_payload, indent=2), encoding="utf-8")
        print(f"Raw API payloads saved to {args.output_json}")


if __name__ == "__main__":
    main()
