import hashlib
import json
import re

import requests
from django.core import signing
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .ai_helper import ACTIONS, MAX_QUESTION_LENGTH, AIError, chat_reply, summarize_sales
from .paypal_client import (
    PayPalError,
    capture_order,
    create_and_send_invoice,
    create_checkout_link,
    get_transactions,
    refund_payment,
)

ACTION_SALT = "seller-assistant-action"  # keeps action tokens separate from other signed data
ACTION_EXPIRY_SECONDS = 600               # a confirm card is valid for 10 minutes
MAX_AMOUNT = 10000                        # safety cap on any single link or invoice
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@ensure_csrf_cookie  # gives the page the security token it needs to POST chat messages
def home(request):
    """The main dashboard page."""
    return render(request, "dashboard/home.html")


def transactions_api(request):
    """Sends the seller's PayPal transactions to the page as JSON."""
    try:
        rows = get_transactions(days=30)
    except PayPalError as e:
        return JsonResponse({"error": str(e)}, status=503)
    except requests.RequestException as e:
        return JsonResponse({"error": f"Couldn't reach PayPal: {e}"}, status=502)
    return JsonResponse({"transactions": rows})


def summary_api(request):
    """Asks the AI to summarise the seller's recent PayPal payments."""
    try:
        rows = get_transactions(days=30)
        summary = summarize_sales(rows)
    except (PayPalError, AIError) as e:
        return JsonResponse({"error": str(e)}, status=503)
    except requests.RequestException as e:
        return JsonResponse({"error": f"Couldn't reach PayPal: {e}"}, status=502)
    return JsonResponse({"summary": summary})


# ------------------------------------------------------------------ Chat + actions

def _check_action(plan, rows):
    """Never trust the AI blindly: check every detail of the action it suggests.
    Returns (action, None) if it's good, or (None, "question to ask the seller")."""
    kind = plan.get("action")
    item = str(plan.get("item") or "").strip()[:120]
    try:
        amount = round(float(plan.get("amount_usd")), 2)
    except (TypeError, ValueError):
        amount = None

    if kind in ("checkout_link", "invoice"):
        if not item:
            return None, "What item is this for?"
        if not amount or amount <= 0 or amount > MAX_AMOUNT:
            return None, f"How much should it be? Please give an amount between $0.01 and ${MAX_AMOUNT:,}."
        if kind == "checkout_link":
            return {"type": kind, "item": item, "amount": amount}, None

        email = str(plan.get("customer_email") or "").strip()
        if not EMAIL_RE.match(email):
            return None, "What's the customer's email address? I need it to send the invoice."
        name = str(plan.get("customer_name") or "").strip()[:80]
        return {"type": "invoice", "item": item, "amount": amount, "email": email, "name": name}, None

    if kind == "refund":
        tid = str(plan.get("transaction_id") or "")
        match = next((r for r in rows if r["id"] == tid), None)
        if not match:
            return None, "I couldn't find that payment. Which one should I refund? Tell me the customer and the item."
        if match["status"] != "Completed" or match["amount"] <= 0:
            return None, "That payment can't be refunded, because it isn't a completed payment."
        return {
            "type": "refund", "transaction_id": tid,
            "customer": match["customer"], "item": match["item"], "amount": match["amount"],
        }, None

    return None, None


def _confirm_card(action):
    """What the seller sees on the confirm card."""
    money = f"${action['amount']:.2f}"
    if action["type"] == "checkout_link":
        return "🔗 Create payment link", [["Item", action["item"]], ["Amount", money]]
    if action["type"] == "invoice":
        who = f"{action['name']} ({action['email']})" if action["name"] else action["email"]
        return "🧾 Send invoice", [["To", who], ["Item", action["item"]], ["Amount", money]]
    return "↩️ Refund payment", [["Customer", action["customer"]], ["Item", action["item"]], ["Refund", money]]


@require_POST
def chat_api(request):
    """Answers the seller's question, or prepares an action for them to confirm."""
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Something went wrong sending your question."}, status=400)

    question = str(body.get("question", "")).strip()
    history = body.get("history", [])
    if not isinstance(history, list):
        history = []

    # Check the question first, so we don't call PayPal for nothing
    if not question:
        return JsonResponse({"error": "Please type a question first."}, status=400)
    if len(question) > MAX_QUESTION_LENGTH:
        return JsonResponse({"error": f"Please keep your question under {MAX_QUESTION_LENGTH} characters."}, status=400)

    try:
        rows = get_transactions(days=30)
        plan = chat_reply(rows, question, history)
    except (PayPalError, AIError) as e:
        return JsonResponse({"error": str(e)}, status=503)
    except requests.RequestException as e:
        return JsonResponse({"error": f"Couldn't reach PayPal: {e}"}, status=502)

    if plan["action"] not in ACTIONS:
        return JsonResponse({"answer": plan["reply"]})

    action, problem = _check_action(plan, rows)
    if problem:
        return JsonResponse({"answer": problem})

    title, details = _confirm_card(action)
    return JsonResponse({
        "answer": plan["reply"],
        "action": {
            "title": title,
            "details": details,
            # The action is signed with the app's SECRET_KEY, so nobody can change
            # the amount or customer between showing the card and pressing Confirm
            "token": signing.dumps(action, salt=ACTION_SALT),
        },
    })


@require_POST
def action_api(request):
    """Runs an action - only after the seller pressed Confirm."""
    try:
        token = str(json.loads(request.body or "{}").get("token", ""))
        action = signing.loads(token, salt=ACTION_SALT, max_age=ACTION_EXPIRY_SECONDS)
    except signing.SignatureExpired:
        return JsonResponse({"error": "This request has expired. Please ask again."}, status=400)
    except (json.JSONDecodeError, signing.BadSignature):
        return JsonResponse({"error": "This request isn't valid. Please ask again."}, status=400)

    # Same token -> same request ID, so a double-click can't do the action twice
    request_id = hashlib.sha256(token.encode()).hexdigest()[:40]

    try:
        if action["type"] == "checkout_link":
            result = create_checkout_link(
                action["item"], action["amount"],
                return_url=request.build_absolute_uri(reverse("paypal_return")),
                cancel_url=request.build_absolute_uri(reverse("home")),
                request_id=request_id,
            )
            return JsonResponse({
                "message": f"✅ Payment link ready for {action['item']} (${action['amount']:.2f}). Share it with your customer:",
                "link": result["link"], "link_text": "Open payment link",
            })

        if action["type"] == "invoice":
            result = create_and_send_invoice(
                action["email"], action["name"], action["item"], action["amount"], request_id=request_id,
            )
            number = f" #{result['invoice_number']}" if result["invoice_number"] else ""
            return JsonResponse({
                "message": f"✅ Invoice{number} for ${action['amount']:.2f} sent to {action['email']}.",
                "link": result["link"], "link_text": "View invoice",
            })

        if action["type"] == "refund":
            refund_payment(action["transaction_id"])
            return JsonResponse({
                "message": f"✅ Refunded ${action['amount']:.2f} to {action['customer']} for {action['item']}. "
                           "It can take a little while to show in your transactions.",
            })
    except PayPalError as e:
        return JsonResponse({"error": str(e)}, status=503)
    except requests.RequestException as e:
        return JsonResponse({"error": f"Couldn't reach PayPal: {e}"}, status=502)

    return JsonResponse({"error": "Unknown action."}, status=400)


def paypal_return(request):
    """PayPal sends the customer here after they approve a payment link.
    We collect the money and show a thank-you page."""
    order_id = request.GET.get("token", "")  # PayPal puts the order ID in ?token=
    try:
        paid = capture_order(order_id)
        error = None if paid else "The payment wasn't completed."
    except PayPalError as e:
        paid, error = False, str(e)
    except requests.RequestException:
        paid, error = False, "Couldn't reach PayPal. Please try again."
    return render(request, "dashboard/paid.html", {"paid": paid, "error": error})