"""Utility script to fetch portfolio positions and trade P&L data from Upstox.

Usage examples:
    python fetch_portfolio_pnl.py
    python fetch_portfolio_pnl.py --from-date 2024-01-01 --to-date 2024-01-31
    python fetch_portfolio_pnl.py --token-file /path/to/token.txt --output-json upstox_dump.json
    python fetch_portfolio_pnl.py --segments EQ FO

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
SEGMENT_CHOICES = ("EQ", "FO", "COM", "CD")


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
        "--financial-year",
        help=(
            "Financial year identifier required by Upstox (e.g., 2223 for FY 2022-23)."
            " Defaults to the FY that covers the chosen to-date."
        ),
    )
    parser.add_argument(
        "--segments",
        nargs="+",
        choices=SEGMENT_CHOICES,
        metavar="SEGMENT",
        help="Segments to include in trade P&L. Default: all segments (EQ FO COM CD).",
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
        "--page-size",
        type=int,
        default=3000,
        help="Number of records per page when fetching trade P&L data (default: 3000).",
    )
    parser.add_argument(
        "--page-number",
        type=int,
        default=1,
        help="Page number to fetch for trade P&L data (default: 1).",
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

        today = date.today()
        default_from = today - timedelta(days=7)
        from_date = ensure_date(args.from_date, default_from)
        to_date = ensure_date(args.to_date, today)

        if from_date > to_date:
            print("from-date cannot be after to-date.")
            raise SystemExit(1)

        def format_trade_date(value: date) -> str:
            return value.strftime("%d-%m-%Y")

        def deduce_financial_year(target_date: date) -> str:
            # Upstox expects YY(YY+1) format e.g., FY 2022-23 -> 2223
            if target_date.month >= 4:
                start_year = target_date.year % 100
            else:
                start_year = (target_date.year - 1) % 100
            end_year = (start_year + 1) % 100
            return f"{start_year:02d}{end_year:02d}"

        financial_year = args.financial_year or deduce_financial_year(to_date)

        base_params: Dict[str, Any] = {
            "from_date": format_trade_date(from_date),
            "to_date": format_trade_date(to_date),
            "financial_year": financial_year,
            "page_number": args.page_number,
            "page_size": args.page_size,
        }
        if args.product_type:
            base_params["product_type"] = args.product_type
        if args.instrument_type:
            base_params["instrument_type"] = args.instrument_type

        segments_to_fetch = args.segments or list(SEGMENT_CHOICES)
        consolidated_pnl: List[Dict[str, Any]] = []
        pnl_by_segment: Dict[str, Any] = {}

        aggregated_metadata: Dict[str, Any] = {}

        for segment in segments_to_fetch:
            segment_params = dict(base_params)
            segment_params["segment"] = segment
            message = (
                f"Fetching trade P&L data for {segment_params['from_date']} to {segment_params['to_date']}"
                f" [segment: {segment}]"
            )
            print(message)

            try:
                metadata_response = api_get(
                    "/trade/profit-loss/metadata", token, params=segment_params
                )
                pnl_metadata_segment = metadata_response.get("data", {})
                pnl_by_segment[f"{segment}_metadata"] = pnl_metadata_segment
                aggregated_metadata[segment] = pnl_metadata_segment

                pnl_data_response = api_get(
                    "/trade/profit-loss/data", token, params=segment_params
                )
                pnl_data = pnl_data_response.get("data", [])
                pnl_by_segment[segment] = pnl_data

                if isinstance(pnl_data, list):
                    for entry in pnl_data:
                        entry.setdefault("segment", segment)
                        entry.setdefault("financial_year", financial_year)
                    consolidated_pnl.extend(pnl_data)
                else:
                    consolidated_pnl.append(
                        {
                            "segment": segment,
                            "financial_year": financial_year,
                            "data": pnl_data,
                        }
                    )
            except RuntimeError as exc:
                print(f"Failed to fetch trade P&L data for segment {segment}: {exc}")

        output_payload["trade_pnl_params"] = {
            **base_params,
            "segments": segments_to_fetch,
        }
        output_payload["trade_pnl_metadata"] = aggregated_metadata
        output_payload["trade_pnl_by_segment"] = pnl_by_segment
        output_payload["trade_pnl_data"] = consolidated_pnl

        if aggregated_metadata:
            print("Available profit & loss metadata (by segment):")
            print(json.dumps(aggregated_metadata, indent=2))

        if consolidated_pnl:
            render_table(
                "Trade Profit & Loss (All Segments)",
                consolidated_pnl,
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
            print("No trade P&L records returned for the requested segments.")

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(output_payload, indent=2), encoding="utf-8")
        print(f"Raw API payloads saved to {args.output_json}")


if __name__ == "__main__":
    main()
