import requests
from django.http import JsonResponse
from django.shortcuts import render

from .ai_helper import AIError, summarize_sales
from .paypal_client import PayPalError, get_transactions


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