"""
paypal_client.py - everything that talks to PayPal lives here.
Keeping it in one file means the rest of the app never touches keys directly.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load keys from the .env file in the main project folder
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
SECRET = os.getenv("PAYPAL_SECRET")
BASE_URL = "https://api-m.sandbox.paypal.com"  # sandbox = fake money

# PayPal uses one-letter status codes; these are friendlier names
STATUS_NAMES = {"S": "Completed", "P": "Pending", "D": "Denied", "V": "Refunded"}


class PayPalError(Exception):
    """A problem we can explain to the user in plain words."""


def get_access_token():
    """Ask PayPal for a temporary access token using our app keys."""
    if not CLIENT_ID or not SECRET:
        raise PayPalError("PayPal keys not found. Check your .env file.")
    response = requests.post(
        f"{BASE_URL}/v1/oauth2/token",
        auth=(CLIENT_ID, SECRET),
        data={"grant_type": "client_credentials"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _money(field):
    """Turn PayPal's {'value': '10.00'} into a number."""
    try:
        return float((field or {}).get("value", 0))
    except (TypeError, ValueError):
        return 0.0


def get_transactions(days=30):
    """Fetch the seller's transactions from the last `days` days (max 31)."""
    token = get_access_token()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=min(days, 31))
    fmt = "%Y-%m-%dT%H:%M:%SZ"

    response = requests.get(
        f"{BASE_URL}/v1/reporting/transactions",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "start_date": start.strftime(fmt),
            "end_date": end.strftime(fmt),
            "fields": "all",
            "page_size": 100,
        },
        timeout=30,
    )

    if response.status_code == 403:
        raise PayPalError(
            "Transaction Search isn't active yet. Make sure it's ticked in your "
            "PayPal app settings - it can take a few hours to start working."
        )
    if not response.ok:
        raise PayPalError(f"PayPal returned an error ({response.status_code}): {response.text[:300]}")

    rows = []
    for t in response.json().get("transaction_details", []):
        info = t.get("transaction_info", {})
        payer = t.get("payer_info", {})
        cart = t.get("cart_info", {})

        # Keep only customer payments (T00..) and refunds/reversals (T11..).
        # This skips things like the sandbox's fake "Initial balance".
        event_code = info.get("transaction_event_code", "")
        if not event_code.startswith(("T00", "T11")):
            continue

        amount = _money(info.get("transaction_amount"))
        fee = _money(info.get("fee_amount"))  # PayPal gives fees as negative numbers

        items = cart.get("item_details") or []
        item = (
            (items[0].get("item_name") if items else None)
            or info.get("transaction_subject")
            or info.get("transaction_note")
            or "Payment"
        )

        name_info = payer.get("payer_name", {})
        customer = (
            name_info.get("alternate_full_name")
            or " ".join(filter(None, [name_info.get("given_name"), name_info.get("surname")]))
            or payer.get("email_address")
            or "Unknown"
        )

        rows.append({
            "id": info.get("transaction_id"),
            "date": info.get("transaction_initiation_date"),
            "customer": customer,
            "email": payer.get("email_address", ""),
            "country": payer.get("country_code", ""),
            "item": item,
            "currency": (info.get("transaction_amount") or {}).get("currency_code", "USD"),
            "amount": amount,
            "fee": abs(fee),
            "net": round(amount + fee, 2),
            "status": (
                "Refunded" if event_code.startswith("T11")
                else STATUS_NAMES.get(info.get("transaction_status"), "Other")
            ),
        })

    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return rows