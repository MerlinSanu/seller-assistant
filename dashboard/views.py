import json

import requests
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .ai_helper import MAX_QUESTION_LENGTH, AIError, answer_question, summarize_sales
from .paypal_client import PayPalError, get_transactions


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


@require_POST
def chat_api(request):
    """Answers the seller's question about their PayPal payments."""
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
        answer = answer_question(rows, question, history)
    except (PayPalError, AIError) as e:
        return JsonResponse({"error": str(e)}, status=503)
    except requests.RequestException as e:
        return JsonResponse({"error": f"Couldn't reach PayPal: {e}"}, status=502)
    return JsonResponse({"answer": answer})