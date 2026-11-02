"""
paypal_client.py - everything that talks to PayPal lives here.
Keeping it in one file means the rest of the app never touches keys directly.
"""

import os
import re
import uuid
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

# PayPal IDs are only letters and numbers - checking this stops anyone
# sneaking odd characters into the web addresses we call
SAFE_ID = re.compile(r"^[A-Za-z0-9-]{5,40}$")


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


def _headers(token, request_id=None):
    """Standard headers. PayPal-Request-Id makes a request safe to repeat:
    if the same ID is sent twice, PayPal does the action only once."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if request_id:
        headers["PayPal-Request-Id"] = request_id
    return headers


def _explain(response, what):
    """Turn a PayPal error into a short sentence and raise it."""
    message = ""
    try:
        data = response.json()
        message = data.get("message") or data.get("error_description") or ""
        details = data.get("details") or []
        if details:
            message += " " + (details[0].get("description") or details[0].get("issue") or "")
    except ValueError:
        message = response.text[:200]
    raise PayPalError(f"PayPal couldn't {what} ({response.status_code}): {message.strip()}")


def _money(field):
    """Turn PayPal's {'value': '10.00'} into a number."""
    try:
        return float((field or {}).get("value", 0))
    except (TypeError, ValueError):
        return 0.0


def _usd(amount):
    return {"currency_code": "USD", "value": f"{amount:.2f}"}


# ---------------------------------------------------------------- Reading

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


# ---------------------------------------------------------------- Actions

def create_checkout_link(item, amount, return_url, cancel_url, request_id=None):
    """Create a PayPal order and return the link the customer opens to pay."""
    token = get_access_token()
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "description": item[:127],
            "amount": {**_usd(amount), "breakdown": {"item_total": _usd(amount)}},
            "items": [{"name": item[:127], "quantity": "1", "unit_amount": _usd(amount)}],
        }],
        "payment_source": {"paypal": {"experience_context": {
            "brand_name": "Seller Assistant",
            "user_action": "PAY_NOW",
            "return_url": return_url,
            "cancel_url": cancel_url,
        }}},
    }
    response = requests.post(
        f"{BASE_URL}/v2/checkout/orders",
        headers=_headers(token, request_id or str(uuid.uuid4())),
        json=body,
        timeout=30,
    )
    if not response.ok:
        _explain(response, "create the payment link")

    data = response.json()
    link = next(
        (l["href"] for l in data.get("links", []) if l.get("rel") in ("payer-action", "approve")),
        None,
    )
    if not link:
        raise PayPalError("PayPal created the order but didn't send back a payment link.")
    return {"order_id": data.get("id"), "link": link}


def capture_order(order_id):
    """Collect the money after the customer approves the payment.
    Returns True if the payment is complete."""
    if not SAFE_ID.match(order_id or ""):
        raise PayPalError("That payment reference doesn't look right.")
    token = get_access_token()
    response = requests.post(
        f"{BASE_URL}/v2/checkout/orders/{order_id}/capture",
        headers=_headers(token, f"capture-{order_id}"),
        json={},
        timeout=30,
    )
    if response.status_code == 422 and "ORDER_ALREADY_CAPTURED" in response.text:
        return True  # already paid - nothing to do
    if not response.ok:
        _explain(response, "complete the payment")
    return response.json().get("status") == "COMPLETED"


def create_and_send_invoice(email, name, item, amount, request_id=None):
    """Create a PayPal invoice and email it to the customer."""
    token = get_access_token()
    rid = request_id or str(uuid.uuid4())

    recipient = {"email_address": email}
    if name:
        first, _, last = name.partition(" ")
        recipient["name"] = {"given_name": first, **({"surname": last} if last else {})}

    body = {
        "detail": {
            "currency_code": "USD",
            "note": "Thank you for your order!",
            "payment_term": {"term_type": "DUE_ON_RECEIPT"},
        },
        "primary_recipients": [{"billing_info": recipient}],
        "items": [{"name": item[:200], "quantity": "1", "unit_amount": _usd(amount)}],
    }

    # 1. Create the invoice (as a draft)
    response = requests.post(
        f"{BASE_URL}/v2/invoicing/invoices",
        headers={**_headers(token, f"{rid}-create"), "Prefer": "return=representation"},
        json=body,
        timeout=30,
    )
    if response.status_code == 403:
        raise PayPalError(
            "Invoicing isn't switched on for your PayPal app. Tick 'Invoicing' under "
            "Features in your app settings on developer.paypal.com."
        )
    if not response.ok:
        _explain(response, "create the invoice")

    data = response.json()
    invoice_id = data.get("id") or (data.get("href") or "").rstrip("/").split("/")[-1]
    if not SAFE_ID.match(invoice_id or ""):
        raise PayPalError("PayPal created the invoice but didn't send back its ID.")

    # 2. Send it to the customer
    sent = requests.post(
        f"{BASE_URL}/v2/invoicing/invoices/{invoice_id}/send",
        headers=_headers(token, f"{rid}-send"),
        json={"send_to_invoicer": False, "send_to_recipient": True},
        timeout=30,
    )
    if not sent.ok:
        _explain(sent, "send the invoice")

    # 3. Look it up again to get the invoice number and the customer's link
    details = requests.get(
        f"{BASE_URL}/v2/invoicing/invoices/{invoice_id}",
        headers=_headers(token),
        timeout=30,
    )
    info = details.json() if details.ok else data
    detail = info.get("detail", {})
    return {
        "invoice_id": invoice_id,
        "invoice_number": detail.get("invoice_number", ""),
        "link": (detail.get("metadata") or {}).get("recipient_view_url"),
    }


def refund_payment(capture_id):
    """Give a customer their money back (full refund)."""
    if not SAFE_ID.match(capture_id or ""):
        raise PayPalError("That payment reference doesn't look right.")
    token = get_access_token()
    response = requests.post(
        f"{BASE_URL}/v2/payments/captures/{capture_id}/refund",
        # Same ID every time for this payment, so it can never be refunded twice by mistake
        headers=_headers(token, f"refund-{capture_id}"),
        json={},
        timeout=30,
    )
    if response.status_code == 422 and "CAPTURE_FULLY_REFUNDED" in response.text:
        raise PayPalError("This payment has already been refunded.")
    if not response.ok:
        _explain(response, "refund the payment")
    data = response.json()
    return {"refund_id": data.get("id"), "status": data.get("status")}