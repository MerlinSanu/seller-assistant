"""
First PayPal sandbox test - PayPal AI Hackathon
------------------------------------------------
What this does (all with FAKE sandbox money):
  1. Logs in to PayPal with your app's Client ID + Secret
  2. Creates a $10 order (like a customer clicking "Buy")
  3. Gives you a link to approve it as a test buyer
  4. Captures the payment (the money "arrives" in your test seller account)
"""

import os
import requests
from dotenv import load_dotenv

# Read your keys from the .env file (never write them directly in code)
load_dotenv()
CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
SECRET = os.getenv("PAYPAL_SECRET")
BASE_URL = "https://api-m.sandbox.paypal.com"  # sandbox = fake money


def get_access_token():
    """Step 1: Ask PayPal for a temporary access token."""
    response = requests.post(
        f"{BASE_URL}/v1/oauth2/token",
        auth=(CLIENT_ID, SECRET),
        data={"grant_type": "client_credentials"},
    )
    response.raise_for_status()
    return response.json()["access_token"]


def create_order(token, amount="10.00", item="Handmade brass lamp (test)"):
    """Step 2: Create an order, like a customer starting checkout."""
    response = requests.post(
        f"{BASE_URL}/v2/checkout/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "description": item,
                    "items": [
                        {
                            "name": item,
                            "quantity": "1",
                            "unit_amount": {"currency_code": "USD", "value": amount},
                        }
                    ],
                    "amount": {
                        "currency_code": "USD",
                        "value": amount,
                        "breakdown": {"item_total": {"currency_code": "USD", "value": amount}},
                    },
                }
            ],
            # Tells PayPal where to send the buyer after approving,
            # and shows a "Pay Now" button instead of "Continue".
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "user_action": "PAY_NOW",
                        "return_url": "https://example.com/payment-success",
                        "cancel_url": "https://example.com/payment-cancelled",
                    }
                }
            },
        },
    )
    response.raise_for_status()
    order = response.json()
    approve_link = next(
        l["href"] for l in order["links"] if l["rel"] in ("approve", "payer-action")
    )
    return order["id"], approve_link


def capture_order(token, order_id):
    """Step 4: Collect the money after the buyer approves."""
    response = requests.post(
        f"{BASE_URL}/v2/checkout/orders/{order_id}/capture",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    if not CLIENT_ID or not SECRET:
        print("❌ Keys not found. Check your .env file.")
        raise SystemExit

    print("🔑 Logging in to PayPal sandbox...")
    token = get_access_token()
    print("✅ Logged in!\n")

    item = input("Item name (press Enter for 'Handmade brass lamp'): ").strip() or "Handmade brass lamp"
    amount = input("Price in USD (press Enter for 10.00): ").strip() or "10.00"
    amount = f"{float(amount):.2f}"

    print(f"\n🛒 Creating a ${amount} order for '{item}'...")
    order_id, approve_link = create_order(token, amount, item)
    print(f"✅ Order created! Order ID: {order_id}\n")

    print("👉 Open this link in your browser and log in as your TEST BUYER:")
    print(f"   {approve_link}\n")
    input("After you click 'Pay' / 'Complete Purchase', come back and press Enter...")

    print("\n💰 Capturing the payment...")
    result = capture_order(token, order_id)
    print(f"✅ Payment status: {result['status']}")
    print("🎉 Done! Check 'Sandbox accounts' -> your business account to see the money.")