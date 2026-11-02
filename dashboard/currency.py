"""
currency.py - turns the seller's US dollars into Indian rupees.

We get today's USD -> INR rate from a free API (no key needed) and remember it
for a few hours, so we don't ask on every page load. If the internet or the API
is down, we use a backup rate from .env, so the dashboard (and the demo!) never
breaks because of the exchange rate.

Rates by Exchange Rate API: https://www.exchangerate-api.com
"""

import os
import time
from datetime import datetime, timezone

import requests

RATE_URL = "https://open.er-api.com/v6/latest/USD"
CACHE_SECONDS = 6 * 60 * 60   # a good rate is reused for 6 hours (the API updates once a day)
RETRY_SECONDS = 10 * 60       # after a failure, wait 10 minutes before asking the API again

# Backup rate if the API can't be reached. Update it in .env now and then.
DEFAULT_FALLBACK_RATE = 95.0

_cache = {"rate": None, "next_check": 0.0}


def _fallback_rate():
    try:
        rate = float(os.getenv("USD_INR_FALLBACK_RATE", DEFAULT_FALLBACK_RATE))
    except ValueError:
        rate = DEFAULT_FALLBACK_RATE
    return {"rate": rate, "live": False, "updated": None}


def _fetch_live_rate():
    """Ask the API for today's rate. Returns None if anything looks wrong."""
    try:
        res = requests.get(RATE_URL, timeout=5)
        data = res.json()
    except (requests.RequestException, ValueError):
        return None

    if data.get("result") != "success":
        return None
    try:
        rate = float(data["rates"]["INR"])
    except (KeyError, TypeError, ValueError):
        return None
    if not 40 <= rate <= 250:  # a silly number means bad data, so don't trust it
        return None

    updated = data.get("time_last_update_unix")
    updated = datetime.fromtimestamp(updated, tz=timezone.utc).isoformat() if updated else None
    return {"rate": round(rate, 4), "live": True, "updated": updated}


def get_usd_inr_rate():
    """Today's USD -> INR rate as {"rate": 94.85, "live": True/False, "updated": ISO date or None}.
    Never raises: falls back to the backup rate if the live one isn't available."""
    now = time.time()
    cached = _cache["rate"]
    if cached and now < _cache["next_check"]:
        return cached

    rate = _fetch_live_rate()
    if rate is None:
        # Keep using an older live rate if we have one, it's better than the backup
        rate = cached if cached and cached["live"] else _fallback_rate()
        _cache["rate"], _cache["next_check"] = rate, now + RETRY_SECONDS
        return rate

    _cache["rate"], _cache["next_check"] = rate, now + CACHE_SECONDS
    return rate


def to_inr(usd, rate):
    """Dollars -> rupees, rounded to whole rupees."""
    return round(float(usd) * rate["rate"])


def format_inr(usd, rate):
    """Dollars -> rupees written the Indian way, e.g. 1234.5 USD -> "₹1,17,082"."""
    rupees = to_inr(usd, rate)
    digits = str(abs(rupees))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups) + "," + tail
    return ("-₹" if rupees < 0 else "₹") + digits
