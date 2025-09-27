import json
from typing import Any, Dict, Optional, Union

import requests
from datetime import datetime


def _normalize_date_input(date_today: Optional[Union[str, datetime]]) -> str:
    if date_today is None:
        return datetime.now().strftime('%Y-%m-%d')
    if isinstance(date_today, datetime):
        return date_today.strftime('%Y-%m-%d')
    return str(date_today)


def market_holiday_date_wise(date_today: Optional[Union[str, datetime]] = None) -> Dict[str, Any]:
    """Fetch market holiday details for the provided date.

    Returns a dictionary with at least ``status`` and ``data`` keys to align with Upstox API responses.
    In case of errors the ``status`` will be ``"error"`` and ``data`` will be an empty list with an
    optional ``message`` describing the failure.
    """

    formatted_date = _normalize_date_input(date_today)
    url = f"https://api.upstox.com/v2/market/holidays/{formatted_date}"
    headers = {"Accept": "application/json"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        return {"status": "error", "data": [], "message": str(exc)}

    try:
        payload: Dict[str, Any] = response.json()
    except ValueError:
        return {"status": "error", "data": [], "message": "Invalid JSON response from Upstox API"}

    # Ensure the payload always exposes a data list for callers
    if "data" not in payload or payload["data"] is None:
        payload["data"] = []

    return payload


if __name__ == "__main__":
    result = market_holiday_date_wise()
    print(json.dumps(result, indent=2, default=str))
