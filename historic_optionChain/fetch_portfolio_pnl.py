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

import upstox_client
from upstox_client.rest import ApiException

DEFAULT_TOKEN_FILENAME = "accessToken_oc.txt"
SEGMENT_CHOICES = ("EQ", "FO", "COM", "CD")
API_VERSION = "2.0"


def create_api_client(access_token: str) -> upstox_client.ApiClient:
    configuration = upstox_client.Configuration()
    configuration.access_token = access_token
    return upstox_client.ApiClient(configuration)


def to_serializable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        return [to_serializable(item) for item in value]
    if isinstance(value, dict):
        return {key: to_serializable(val) for key, val in value.items()}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def to_dict_list(items: Optional[Iterable[Any]]) -> List[Dict[str, Any]]:
    if not items:
        return []
    result: List[Dict[str, Any]] = []
    for item in items:
        converted = to_serializable(item) or {}
        if isinstance(converted, dict):
            result.append(converted)
        else:
            result.append({"value": converted})
    return result


def load_access_token(token_path: Path) -> str:
    if not token_path.exists():
        raise FileNotFoundError(
            f"Access token file not found at {token_path}. Run loginCLI.py first or supply --token-file."
        )

    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError(f"Access token file at {token_path} is empty.")
    return token

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

    api_client = create_api_client(token)
    portfolio_api = upstox_client.PortfolioApi(api_client)
    trade_pnl_api = None if args.skip_pnl else upstox_client.TradeProfitAndLossApi(api_client)

    print("\n==== Portfolio Snapshot ====")

    short_positions: List[Dict[str, Any]] = []
    long_holdings: List[Dict[str, Any]] = []

    try:
        positions_response = portfolio_api.get_positions(API_VERSION)
        if getattr(positions_response, "status", "").lower() != "success":
            raise RuntimeError(f"Positions API returned status {getattr(positions_response, 'status', None)}")
        short_positions = to_dict_list(getattr(positions_response, "data", []))

        holdings_response = portfolio_api.get_holdings(API_VERSION)
        if getattr(holdings_response, "status", "").lower() != "success":
            raise RuntimeError(f"Holdings API returned status {getattr(holdings_response, 'status', None)}")
        long_holdings = to_dict_list(getattr(holdings_response, "data", []))

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
    except (RuntimeError, ApiException) as exc:
        print(f"Failed to fetch portfolio data: {exc}")
        raise SystemExit(1) from exc

    output_payload: Dict[str, Any] = {
        "short_term_positions": short_positions,
        "long_term_holdings": long_holdings,
    }

    if not args.skip_pnl:
        if trade_pnl_api is None:
            trade_pnl_api = upstox_client.TradeProfitAndLossApi(api_client)
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
        if args.product_type or args.instrument_type:
            print(
                "Note: product_type and instrument_type filters are not supported by the Upstox SDK "
                "Trade Profit & Loss endpoints and will be ignored."
            )
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
                metadata_response = trade_pnl_api.get_trade_wise_profit_and_loss_meta_data(
                    segment,
                    financial_year,
                    API_VERSION,
                    from_date=segment_params["from_date"],
                    to_date=segment_params["to_date"],
                )
                if getattr(metadata_response, "status", "").lower() != "success":
                    raise RuntimeError(
                        f"Metadata API returned status {getattr(metadata_response, 'status', None)}"
                    )
                pnl_metadata_segment = to_serializable(getattr(metadata_response, "data", {})) or {}
                pnl_by_segment[f"{segment}_metadata"] = pnl_metadata_segment
                aggregated_metadata[segment] = pnl_metadata_segment

                data_response = trade_pnl_api.get_trade_wise_profit_and_loss_data(
                    segment,
                    financial_year,
                    args.page_number,
                    args.page_size,
                    API_VERSION,
                    from_date=segment_params["from_date"],
                    to_date=segment_params["to_date"],
                )
                if getattr(data_response, "status", "").lower() != "success":
                    raise RuntimeError(
                        f"Data API returned status {getattr(data_response, 'status', None)}"
                    )
                pnl_data = to_serializable(getattr(data_response, "data", [])) or []
                pnl_by_segment[segment] = pnl_data

                if isinstance(pnl_data, list):
                    for entry in pnl_data:
                        if isinstance(entry, dict):
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
            except (RuntimeError, ApiException) as exc:
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
