"""
translations.py - the app's fixed messages in English, Hindi and Malayalam.

The AI writes its own replies in the chosen language. These are the messages
our Python code writes itself (questions, confirm cards, "done" messages).
"""

# code -> (name for the AI, script it should write in)
LANGUAGES = {
    "en": ("English", "Latin"),
    "hi": ("Hindi", "Devanagari"),
    "ml": ("Malayalam", "Malayalam"),
}

TEXT = {
    "en": {
        "ask_item": "What item is this for?",
        "ask_amount": "How much should it be? Please give an amount between $0.01 and ${max}.",
        "ask_email": "What's the customer's email address? I need it to send the invoice.",
        "refund_not_found": "I couldn't find that payment. Which one should I refund? Tell me the customer and the item.",
        "refund_not_completed": "That payment can't be refunded, because it isn't a completed payment.",
        "card_link": "🔗 Create payment link",
        "card_invoice": "🧾 Send invoice",
        "card_refund": "↩️ Refund payment",
        "lbl_item": "Item", "lbl_amount": "Amount", "lbl_to": "To", "lbl_customer": "Customer", "lbl_refund": "Refund",
        "done_link": "✅ Payment link ready for {item} ({amount}). Share it with your customer:",
        "done_invoice": "✅ Invoice{number} for {amount} sent to {email}.",
        "done_refund": "✅ Refunded {amount} to {customer} for {item}. It can take a little while to show in your transactions.",
        "open_link": "Open payment link",
        "view_invoice": "View invoice",
    },
    "hi": {
        "ask_item": "यह किस सामान के लिए है?",
        "ask_amount": "कितनी राशि रखनी है? कृपया $0.01 से ${max} के बीच की राशि बताएँ।",
        "ask_email": "ग्राहक का ईमेल पता क्या है? इनवॉइस भेजने के लिए इसकी ज़रूरत है।",
        "refund_not_found": "वह भुगतान नहीं मिला। किसका रिफ़ंड करना है? ग्राहक और सामान का नाम बताएँ।",
        "refund_not_completed": "इस भुगतान का रिफ़ंड नहीं हो सकता, क्योंकि यह पूरा हुआ भुगतान नहीं है।",
        "card_link": "🔗 पेमेंट लिंक बनाएँ",
        "card_invoice": "🧾 इनवॉइस भेजें",
        "card_refund": "↩️ भुगतान रिफ़ंड करें",
        "lbl_item": "सामान", "lbl_amount": "राशि", "lbl_to": "किसे", "lbl_customer": "ग्राहक", "lbl_refund": "रिफ़ंड",
        "done_link": "✅ {item} ({amount}) के लिए पेमेंट लिंक तैयार है। इसे अपने ग्राहक को भेजें:",
        "done_invoice": "✅ {amount} का इनवॉइस{number} {email} को भेज दिया गया।",
        "done_refund": "✅ {customer} को {item} के लिए {amount} रिफ़ंड कर दिया गया। लेन-देन में दिखने में थोड़ा समय लग सकता है।",
        "open_link": "पेमेंट लिंक खोलें",
        "view_invoice": "इनवॉइस देखें",
    },
    "ml": {
        "ask_item": "ഇത് ഏത് സാധനത്തിനാണ്?",
        "ask_amount": "എത്ര തുക വേണം? $0.01 മുതൽ ${max} വരെയുള്ള ഒരു തുക പറയൂ.",
        "ask_email": "ഉപഭോക്താവിന്റെ ഇമെയിൽ വിലാസം എന്താണ്? ഇൻവോയ്സ് അയയ്ക്കാൻ അത് വേണം.",
        "refund_not_found": "ആ പേയ്‌മെന്റ് കണ്ടെത്താനായില്ല. ഏതാണ് റീഫണ്ട് ചെയ്യേണ്ടത്? ഉപഭോക്താവിന്റെയും സാധനത്തിന്റെയും പേര് പറയൂ.",
        "refund_not_completed": "ഈ പേയ്‌മെന്റ് പൂർത്തിയായതല്ലാത്തതിനാൽ റീഫണ്ട് ചെയ്യാനാകില്ല.",
        "card_link": "🔗 പേയ്‌മെന്റ് ലിങ്ക് ഉണ്ടാക്കുക",
        "card_invoice": "🧾 ഇൻവോയ്സ് അയയ്ക്കുക",
        "card_refund": "↩️ പേയ്‌മെന്റ് റീഫണ്ട് ചെയ്യുക",
        "lbl_item": "സാധനം", "lbl_amount": "തുക", "lbl_to": "ആർക്ക്", "lbl_customer": "ഉപഭോക്താവ്", "lbl_refund": "റീഫണ്ട്",
        "done_link": "✅ {item} ({amount}) എന്നതിനുള്ള പേയ്‌മെന്റ് ലിങ്ക് തയ്യാർ. ഇത് ഉപഭോക്താവുമായി പങ്കിടൂ:",
        "done_invoice": "✅ {amount}-ന്റെ ഇൻവോയ്സ്{number} {email}-ലേക്ക് അയച്ചു.",
        "done_refund": "✅ {customer}-ന് {item}-നുള്ള {amount} റീഫണ്ട് ചെയ്തു. ഇടപാടുകളിൽ കാണാൻ കുറച്ച് സമയമെടുത്തേക്കാം.",
        "open_link": "പേയ്‌മെന്റ് ലിങ്ക് തുറക്കുക",
        "view_invoice": "ഇൻവോയ്സ് കാണുക",
    },
}


def clean_lang(code):
    """Only allow languages we support; anything else becomes English."""
    return code if code in LANGUAGES else "en"


def t(lang, key, **values):
    """Get a message in the chosen language, with {values} filled in."""
    text = TEXT[clean_lang(lang)].get(key) or TEXT["en"][key]
    return text.format(**values) if values else text
