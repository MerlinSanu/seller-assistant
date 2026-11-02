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
from .currency import format_inr, get_usd_inr_rate
from .translations import clean_lang, t
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
    # The page uses the rate for its USD / ₹ toggle
    return JsonResponse({"transactions": rows, "rate": get_usd_inr_rate()})


def summary_api(request):
    """Asks the AI to summarise the seller's recent PayPal payments."""
    try:
        rows = get_transactions(days=30)
        lang = clean_lang(request.GET.get("lang", "en"))
        summary = summarize_sales(rows, lang=lang, rate=get_usd_inr_rate())
    except (PayPalError, AIError) as e:
        return JsonResponse({"error": str(e)}, status=503)
    except requests.RequestException as e:
        return JsonResponse({"error": f"Couldn't reach PayPal: {e}"}, status=502)
    return JsonResponse({"summary": summary})


# ------------------------------------------------------------------ Chat + actions

def _check_action(plan, rows, lang="en"):
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
            return None, t(lang, "ask_item")
        if not amount or amount <= 0 or amount > MAX_AMOUNT:
            return None, t(lang, "ask_amount", max=f"{MAX_AMOUNT:,}")
        if kind == "checkout_link":
            return {"type": kind, "item": item, "amount": amount}, None

        email = str(plan.get("customer_email") or "").strip()
        if not EMAIL_RE.match(email):
            return None, t(lang, "ask_email")
        name = str(plan.get("customer_name") or "").strip()[:80]
        return {"type": "invoice", "item": item, "amount": amount, "email": email, "name": name}, None

    if kind == "refund":
        tid = str(plan.get("transaction_id") or "")
        match = next((r for r in rows if r["id"] == tid), None)
        if not match:
            return None, t(lang, "refund_not_found")
        if match["status"] != "Completed" or match["amount"] <= 0:
            return None, t(lang, "refund_not_completed")
        return {
            "type": "refund", "transaction_id": tid,
            "customer": match["customer"], "item": match["item"], "amount": match["amount"],
        }, None

    return None, None


def _confirm_card(action, rate, lang="en"):
    """What the seller sees on the confirm card (dollars, with rupees alongside)."""
    money = f"${action['amount']:.2f}  (≈ {format_inr(action['amount'], rate)})"
    item, amount = [t(lang, "lbl_item"), action["item"]], [t(lang, "lbl_amount"), money]
    if action["type"] == "checkout_link":
        return t(lang, "card_link"), [item, amount]
    if action["type"] == "invoice":
        who = f"{action['name']} ({action['email']})" if action["name"] else action["email"]
        return t(lang, "card_invoice"), [[t(lang, "lbl_to"), who], item, amount]
    return t(lang, "card_refund"), [[t(lang, "lbl_customer"), action["customer"]], item, [t(lang, "lbl_refund"), money]]


@require_POST
def chat_api(request):
    """Answers the seller's question, or prepares an action for them to confirm."""
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Something went wrong sending your question."}, status=400)

    question = str(body.get("question", "")).strip()
    lang = clean_lang(body.get("lang", "en"))
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
        rate = get_usd_inr_rate()
        plan = chat_reply(rows, question, history, lang=lang, rate=rate)
    except (PayPalError, AIError) as e:
        return JsonResponse({"error": str(e)}, status=503)
    except requests.RequestException as e:
        return JsonResponse({"error": f"Couldn't reach PayPal: {e}"}, status=502)

    if plan["action"] not in ACTIONS:
        return JsonResponse({"answer": plan["reply"]})

    action, problem = _check_action(plan, rows, lang)
    if problem:
        return JsonResponse({"answer": problem})

    action["lang"] = lang  # so the "done" message after Confirm is in the same language
    title, details = _confirm_card(action, rate, lang)
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

    lang = clean_lang(action.get("lang", "en"))
    money = f"${action['amount']:.2f}"

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
                "message": t(lang, "done_link", item=action["item"], amount=money),
                "link": result["link"], "link_text": t(lang, "open_link"),
            })

        if action["type"] == "invoice":
            result = create_and_send_invoice(
                action["email"], action["name"], action["item"], action["amount"], request_id=request_id,
            )
            number = f" #{result['invoice_number']}" if result["invoice_number"] else ""
            return JsonResponse({
                "message": t(lang, "done_invoice", number=number, amount=money, email=action["email"]),
                "link": result["link"], "link_text": t(lang, "view_invoice"),
            })

        if action["type"] == "refund":
            refund_payment(action["transaction_id"])
            return JsonResponse({
                "message": t(lang, "done_refund", amount=money, customer=action["customer"], item=action["item"]),
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