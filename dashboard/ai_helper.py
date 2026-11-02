"""
ai_helper.py - everything that talks to the AI (Gemini) lives here.

Important idea: we calculate the numbers ourselves in Python and give them
to the AI. The AI only turns them into friendly words. This stops the AI
from making maths mistakes or inventing numbers.
"""

import json
import os
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# You can change the model in .env later without touching code
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")


class AIError(Exception):
    """A problem with the AI we can explain in plain words."""


_CLIENT = None


def _client():
    """Create the Gemini client once and keep reusing it
    (creating a fresh one each time can get closed before it's used)."""
    global _CLIENT
    if _CLIENT is None:
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise AIError("Gemini API key not found. Add GEMINI_API_KEY to your .env file.")
        _CLIENT = genai.Client(api_key=key)
    return _CLIENT


def calculate_totals(rows):
    """Work out the key numbers from the transactions (done in Python, not AI)."""
    completed = [r for r in rows if r["status"] == "Completed" and r["amount"] > 0]

    revenue = round(sum(r["amount"] for r in completed), 2)
    fees = round(sum(r["fee"] for r in completed), 2)
    net = round(sum(r["net"] for r in completed), 2)

    by_item = defaultdict(float)
    for r in completed:
        by_item[r["item"]] += r["amount"]
    top_item = max(by_item, key=by_item.get) if by_item else None

    return {
        "completed_payments": len(completed),
        "total_revenue_usd": revenue,
        "total_fees_usd": fees,
        "seller_keeps_usd": net,
        "fee_percent": round(fees / revenue * 100, 1) if revenue else 0,
        "top_item": top_item,
        "top_item_revenue_usd": round(by_item[top_item], 2) if top_item else 0,
        "pending_payments": sum(1 for r in rows if r["status"] == "Pending"),
        "refunded_payments": sum(1 for r in rows if r["status"] == "Refunded"),
        "denied_payments": sum(1 for r in rows if r["status"] == "Denied"),
    }


def summarize_sales(rows, language="English"):
    """Ask Gemini for a short, friendly summary of the seller's payments."""
    if not rows:
        return "No payments in the last 30 days yet. Once customers start paying, I'll summarise them here."

    totals = calculate_totals(rows)
    recent = [
        {"date": r["date"][:10] if r["date"] else "", "item": r["item"],
         "amount_usd": r["amount"], "country": r["country"], "status": r["status"]}
        for r in rows[:50]
    ]

    prompt = f"""You are a friendly business assistant for a small Indian seller who sells
handmade products to customers abroad and gets paid through PayPal.

Write a short summary of their recent PayPal sales in {language}.

Rules:
- 2 to 3 sentences, under 70 words.
- Use ONLY the numbers given below. Do not calculate new numbers or invent anything.
- Mention how much they earned, their top item, and how much went to PayPal fees.
- If there are pending, refunded or denied payments, mention it briefly as something to check.
- Warm, simple, everyday words. No markdown, no bullet points, no greeting like "Hi".

Totals (already calculated, USD):
{json.dumps(totals, indent=2)}

Recent transactions:
{json.dumps(recent, indent=2)}
"""

    try:
        client = _client()
        response = client.models.generate_content(model=MODEL, contents=prompt)
    except AIError:
        raise
    except Exception as e:
        raise AIError(f"The AI couldn't respond right now ({e}).")

    text = (response.text or "").strip()
    if not text:
        raise AIError("The AI returned an empty answer. Try refreshing.")
    return text