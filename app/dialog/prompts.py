"""Every spoken / shown prompt, keyed by id, in Tamil and English. {app} is APP_NAME.

NEXT_STEPS lines (NS_*) are victim guidance. Each needs an official source in docs/NEXT_STEPS_SOURCES.md;
NEXT_STEPS_SOURCED lists the ones that have one. The rest carry a "draft guidance" tag in DEMO_MODE."""

from functools import lru_cache

from app.config import get_settings

PROMPTS: dict[str, dict[str, str]] = {
    "OPENING": {
        "ta": "வணக்கம். நான் {app}, ஒரு AI உதவியாளர். நான் போலீஸ் இல்லை, பணத்தை முடக்கவும் முடியாது. "
              "இன்னும் பேங்க்கு அல்லது 1930-க்கு கால் பண்ணலைன்னா, உடனே பண்ணுங்க. "
              "நான் OTP, PIN எதுவும் கேட்க மாட்டேன். என்ன நடந்தது என்று சொல்லுங்க.",
        "en": "Hello, I am {app}, an AI assistant. I am not the police and I cannot freeze money. "
              "If you have not called your bank or 1930 yet, please do it now. "
              "I will never ask for an OTP or PIN. Tell me what happened.",
    },
    "ASK_amount": {"ta": "எவ்வளவு பணம் போச்சு?", "en": "How much money was lost?"},
    "ASK_victim_bank": {"ta": "எந்த பேங்க் அக்கவுண்ட்ல இருந்து பணம் போச்சு?", "en": "Which bank was the money taken from?"},
    "ASK_payment_mode": {"ta": "பணம் எப்படி போச்சு? UPI-யா, கார்டா, நெட் பேங்கிங்கா?",
                         "en": "How did the money go? UPI, card, or net banking?"},
    "ASK_suspect_bank": {"ta": "பணம் போன அக்கவுண்ட் எந்த பேங்க்னு தெரியுமா? தெரியலைன்னா 'தெரியல' சொல்லுங்க.",
                         "en": "Do you know which bank the money went to? If not, say 'don't know'."},
    "ASK_called_bank": {"ta": "இதைப் பற்றி உங்க பேங்க்கு ஏற்கனவே கால் பண்ணீங்களா?",
                        "en": "Have you already called your bank about this?"},
    "ASK_MORE_TXN": {"ta": "இன்னொரு transaction இருக்கா?", "en": "Was there any other transaction?"},
    "TXN_PREFIX": {"ta": "பரிவர்த்தனை {n}: ", "en": "Transaction {n}: "},
    "MORE_TXN_EXPECTED": {"ta": "நீங்க {n} தடவை பணம் போச்சுன்னு சொன்னீங்க.", "en": "You said money went {n} times."},
    "DUP_UTR": {"ta": "இந்த UTR நம்பர் முன்னாடி சொன்ன transaction-ஓடது மாதிரி இருக்கு. இது அதே transaction-ஆ?",
                "en": "This UTR matches a transaction you already gave. Is this the same transaction?"},
    "DUP_DROPPED": {"ta": "சரி, அதை ஒரு முறை மட்டும் எடுத்துக்கறேன்.", "en": "Okay, I will count it only once."},
    "MAX_TXNS": {"ta": "இதற்கு மேல் transaction-களை அதிகாரி சேர்ப்பார்.",
                 "en": "An officer will add any further transactions."},
    "ASK_datetime": {"ta": "இது எப்போ நடந்தது? நாள், நேரம் சொல்லுங்கள்.", "en": "When did this happen? Say the day and time."},
    "ASK_utr": {
        "ta": "பேங்க் SMS-ல உள்ள பன்னிரண்டு இலக்க UTR நம்பர். SMS-ஐ பேஸ்ட் பண்ணுங்க, டைப் பண்ணுங்க, அல்லது சொல்லுங்க.",
        "en": "The 12-digit UTR or reference number from the bank SMS. Paste the SMS, type it, or say it.",
    },
    "ASK_suspect_phone": {"ta": "உங்களுக்கு கால் வந்த நம்பர் என்ன?", "en": "What number did the fraudster call from?"},
    "ASK_suspect_upi": {
        "ta": "பணம் அனுப்பின UPI ஐடி தெரியுமா? தெரியலைன்னா 'தெரியல' என்று சொல்லுங்கள்.",
        "en": "Do you know the UPI ID the money went to? If not, say 'don't know'.",
    },
    "ASK_victim_name": {"ta": "உங்கள் பெயர் என்ன?", "en": "What is your name?"},
    "ASK_victim_mobile": {"ta": "உங்கள் மொபைல் நம்பர் என்ன?", "en": "What is your mobile number?"},
    "ASK_district": {"ta": "நீங்கள் எந்த மாவட்டம்?", "en": "Which district are you in?"},
    "DIDNT_CATCH": {"ta": "மன்னிக்கவும், சரியா புரியல. மறுபடி சொல்லுங்க, அல்லது கீபேட் பயன்படுத்துங்க.",
                    "en": "Sorry, I didn't catch that. Please say it again, or use the keypad."},
    "SILENCE": {"ta": "எதுவும் கேட்கல. பட்டனை அழுத்தி பேசுங்க.", "en": "I didn't hear anything. Hold the button and speak."},
    "WRONG_LEN_utr": {"ta": "நான் {n} இலக்கம் கேட்டேன். UTR பன்னிரண்டு இலக்கம். மறுபடி சொல்லுங்க, அல்லது SMS பேஸ்ட் பண்ணுங்க.",
                      "en": "I heard {n} digits. A UTR has 12. Please say it again, or paste the SMS."},
    "WRONG_LEN_phone": {"ta": "நான் {n} இலக்கம் கேட்டேன். மொபைல் நம்பர் பத்து இலக்கம். மறுபடி சொல்லுங்க.",
                        "en": "I heard {n} digits. A mobile number has 10. Please say it again."},
    "CORRECT_CHUNK": {"ta": "சரியான இலக்கங்களை சொல்லுங்க, அல்லது கீபேட்ல டைப் பண்ணுங்க.",
                      "en": "Please say the correct digits for this part, or type them on the keypad."},
    "CONFIRM_HINT": {"ta": "சரி என்றால் 'ஆமா', தப்பு என்றால் 'இல்ல' சொல்லுங்க, அல்லது ✓ ✗ பட்டனை அழுத்துங்க.",
                     "en": "Say 'yes' if it is right or 'no' if it is wrong, or press ✓ or ✗."},
    "USE_NUMPAD": {"ta": "கீபேட்ல டைப் பண்ணுங்க.", "en": "Please type it on the keypad."},
    "READBACK": {"ta": "{label}: {words}. சரியா?", "en": "{label}: {words}. Is that right?"},
    "HIGH_AMOUNT": {"ta": "இது பத்து லட்சத்துக்கு மேல். தொகையை ஒருமுறை திரையில் சரிபாருங்க.",
                    "en": "This is above ten lakh. Please check the amount on screen once more."},
    "OLD_DATE": {"ta": "ஏழு நாளுக்கு மேல் ஆகிவிட்டது. பணம் திரும்ப கிடைப்பது கடினம், ஆனாலும் புகார் கொடுங்க.",
                 "en": "It has been more than 7 days. Freezing the money is less likely, but still report it."},
    "UNCONFIRMED": {"ta": "பரவாயில்லை, இதை அதிகாரி சரிபார்க்கும்படி குறிக்கிறேன்.",
                    "en": "That's okay, I'll mark this for the officer to verify."},
    "SKIPPED": {"ta": "சரி, அடுத்தது.", "en": "Okay, next."},
    "NEVER_SHARE_OTP": {"ta": "OTP, PIN, CVV அல்லது பாஸ்வேர்ட் யாரிடமும் சொல்ல வேண்டாம், என்னிடமும் கூட. அதை நான் சேமிக்கவில்லை.",
                        "en": "Never share an OTP, PIN, CVV or password with anyone, including me. I did not keep it."},
    "SMS_THANKS": {"ta": "SMS-ல இருந்து விவரங்களை எடுத்துட்டேன். திரையில் பாருங்க.",
                   "en": "I took the details from the SMS. Please check them on screen."},
    "REVIEW": {"ta": "மொத்தம் {n} transaction, {total}. எல்லாம் சரியா?",
               "en": "{n} transactions, total {total}. Is everything correct?"},
    "REVIEW_FIX": {"ta": "திரையில் தப்பான விவரத்தை தொட்டு சரி பண்ணுங்க, அல்லது 'ஆள் வேணும்' சொல்லுங்க.",
                   "en": "Tap the wrong detail on screen to fix it, or say 'officer' to talk to a person."},
    "QUEUED": {"ta": "நன்றி. உங்க விவரங்கள் ஒரு அதிகாரியின் சரிபார்ப்புக்கு அனுப்பப்பட்டன. உங்க வரைவு எண் திரையில் உள்ளது.",
               "en": "Thank you. Your details are sent to an officer for review. Your draft reference is on screen."},
    "NS_CALL_BANK": {"ta": "உடனே உங்க பேங்க் ஹெல்ப்லைனுக்கு கால் பண்ணி மோசடியை சொல்லி, கார்டு, UPI-ஐ பிளாக் பண்ண சொல்லுங்க.",
                     "en": "Call your bank's helpline now, report the fraud, and ask them to block your card and UPI."},
    "NS_CALL_1930": {"ta": "இன்னும் பண்ணலைன்னா, 1930-க்கு கால் பண்ணி இந்த சுருக்கத்தை சொல்லுங்க.",
                     "en": "If you have not already, call 1930 and give them this summary."},
    "NS_KEEP_EVIDENCE": {"ta": "SMS, கால் லிஸ்ட், சாட் எதையும் அழிக்காதீங்க. ஸ்கிரீன்ஷாட் எடுத்து வெச்சுக்கோங்க.",
                         "en": "Do not delete SMS, call logs or chats. Take screenshots."},
    "NS_CHANGE_PIN": {"ta": "உங்க சொந்த போனிலிருந்து நெட் பேங்கிங், UPI PIN-ஐ மாத்துங்க.",
                      "en": "Change your net-banking password and UPI PIN from your own phone."},
    "NS_RECOVERY_SCAM": {"ta": "பணத்தை திரும்ப வாங்கித் தர்றோம்னு கட்டணம் கேட்கறவங்க இன்னொரு மோசடி.",
                         "en": "Anyone who offers to recover your money for a fee is another scam."},
    "HANDOFF_HUMAN": {"ta": "உங்களை ஒரு அதிகாரியிடம் இணைக்கிறேன் (டெமோவில் இது மாதிரி மட்டும்). தயவு செய்து 1930-க்கும் கால் பண்ணுங்க.",
                      "en": "Connecting you to an officer (simulated in demo). Please also call 1930."},
    "HANDOFF_NONFIN": {"ta": "இதற்கு ஒரு அதிகாரி உதவுவார். 1930-க்கு கால் பண்ணுங்க அல்லது cybercrime.gov.in-ல் புகார் கொடுங்க. நீங்கள் தனியாக இல்லை.",
                       "en": "An officer will help with this. Please call 1930 or report at cybercrime.gov.in. You are not alone."},
    "HANDOFF_WELLBEING": {"ta": "நீங்கள் முக்கியம். இப்போதே Tele-MANAS 14416-க்கு கால் பண்ணுங்க. பண விஷயத்திற்கு 1930.",
                          "en": "You matter. Please call Tele-MANAS on 14416 now. For the money, call 1930."},
    "RATE_LIMITED": {"ta": "இப்போது சேவை பிஸியாக உள்ளது. நேரடியாக 1930-க்கு கால் பண்ணுங்க.",
                     "en": "The service is busy right now. Please call 1930 directly."},
    "TOO_LONG": {"ta": "கொஞ்சம் சுருக்கமா, 25 விநாடிக்குள் சொல்லுங்க.", "en": "Please keep it shorter, under 25 seconds."},

    # Phone calls have no screen. text() prefers PHONE_<id> over <id> on that channel.
    "PHONE_OPENING": {
        "ta": "வணக்கம். இது சோதனை நிலையில் உள்ள டெலிபோன் சேவை. இது டெமோ, உண்மையான விவரங்களை சொல்ல வேண்டாம். "
              "நான் {app}, ஒரு AI உதவியாளர். நான் போலீஸ் இல்லை, பணத்தை முடக்கவும் முடியாது. "
              "இன்னும் பேங்க்கு அல்லது 1930-க்கு கால் பண்ணலைன்னா, உடனே பண்ணுங்க. "
              "நான் OTP, PIN எதுவும் கேட்க மாட்டேன். "
              "சரி என்றால் ஒன்று, தப்பு என்றால் இரண்டு, மறுபடி கேட்க மூன்று, அதிகாரியிடம் பேச பூஜ்ஜியம் அழுத்துங்க. "
              "என்ன நடந்தது என்று சொல்லுங்க.",
        "en": "Hello. This is an experimental telephone service and a demo, so do not give real details. "
              "I am {app}, an AI assistant. I am not the police and I cannot freeze money. "
              "If you have not called your bank or 1930 yet, please do it now. I will never ask for an OTP or PIN. "
              "Press 1 for yes, 2 for no, 3 to repeat, and 0 for an officer. Tell me what happened.",
    },
    "PHONE_ASK_utr": {
        "ta": "பேங்க் SMS-ல உள்ள பன்னிரண்டு இலக்க UTR நம்பரை சொல்லுங்க. அல்லது ஸ்டார் அழுத்தி டைப் பண்ணி, கடைசியில் ஹாஷ் அழுத்துங்க.",
        "en": "Say the 12-digit UTR number from the bank SMS. Or press star, type it, then press hash.",
    },
    "PHONE_DIDNT_CATCH": {"ta": "மன்னிக்கவும், சரியா புரியல. மறுபடி சொல்லுங்க.",
                          "en": "Sorry, I didn't catch that. Please say it again."},
    "PHONE_SILENCE": {"ta": "எதுவும் கேட்கல. தயவு செய்து பேசுங்க.", "en": "I didn't hear anything. Please speak now."},
    "PHONE_WRONG_LEN_utr": {"ta": "நான் {n} இலக்கம் கேட்டேன். UTR பன்னிரண்டு இலக்கம். மறுபடி சொல்லுங்க, அல்லது ஸ்டார் அழுத்தி டைப் பண்ணுங்க.",
                            "en": "I heard {n} digits. A UTR has 12. Please say it again, or press star and type it."},
    "PHONE_CORRECT_CHUNK": {"ta": "சரியான இலக்கங்களை சொல்லுங்க, அல்லது டைப் பண்ணி ஹாஷ் அழுத்துங்க.",
                            "en": "Please say the correct digits for this part, or type them and press hash."},
    "PHONE_CONFIRM_HINT": {"ta": "சரி என்றால் ஒன்று, தப்பு என்றால் இரண்டு அழுத்துங்க.",
                           "en": "Press 1 if it is right, or 2 if it is wrong."},
    "PHONE_USE_NUMPAD": {"ta": "கீபேட்ல டைப் பண்ணி, கடைசியில் ஹாஷ் அழுத்துங்க.",
                         "en": "Please type it on the keypad, then press hash."},
    "PHONE_HIGH_AMOUNT": {"ta": "இது பத்து லட்சத்துக்கு மேல். தொகையை கவனமா கேட்டு சரிபாருங்க.",
                          "en": "This is above ten lakh. Please listen carefully and check the amount."},
    "PHONE_REVIEW_FIX": {"ta": "ஏதாவது தப்புன்னா, அதிகாரியிடம் பேச பூஜ்ஜியம் அழுத்துங்க. அப்படியே அனுப்ப ஒன்று அழுத்துங்க.",
                         "en": "If something is wrong, press 0 for an officer. To send it as it is, press 1."},
    "PHONE_QUEUED": {"ta": "நன்றி. உங்க விவரங்கள் ஒரு அதிகாரியின் சரிபார்ப்புக்கு அனுப்பப்பட்டன.",
                     "en": "Thank you. Your details are sent to an officer for review."},
    "PHONE_REFERENCE": {"ta": "உங்க வரைவு குறிப்பு எண் {ref}. இது போலீஸ் எண் அல்ல.",
                        "en": "Your draft reference is {ref}. This is not a police number."},
}

LABELS: dict[str, dict[str, str]] = {
    "amount": {"ta": "தொகை", "en": "Amount"},
    "victim_bank": {"ta": "உங்க பேங்க்", "en": "Your bank"},
    "payment_mode": {"ta": "பணம் போன வழி", "en": "Payment mode"},
    "suspect_bank": {"ta": "பணம் போன பேங்க்", "en": "Receiving bank"},
    "called_bank": {"ta": "பேங்க்கு கால் பண்ணியது", "en": "Called your bank"},
    "datetime": {"ta": "நேரம்", "en": "Date and time"},
    "utr": {"ta": "UTR நம்பர்", "en": "UTR number"},
    "suspect_phone": {"ta": "கால் வந்த நம்பர்", "en": "Caller's number"},
    "suspect_upi": {"ta": "UPI ஐடி", "en": "UPI ID"},
    "victim_name": {"ta": "உங்கள் பெயர்", "en": "Your name"},
    "victim_mobile": {"ta": "உங்கள் மொபைல்", "en": "Your mobile"},
    "district": {"ta": "மாவட்டம்", "en": "District"},
}

NEXT_STEPS = ["NS_CALL_BANK", "NS_CALL_1930", "NS_KEEP_EVIDENCE", "NS_CHANGE_PIN", "NS_RECOVERY_SCAM"]
# Lines with an official source recorded in docs/NEXT_STEPS_SOURCES.md. Others show "draft guidance" in DEMO_MODE.
NEXT_STEPS_SOURCED: set[str] = set()

STATIC_PROMPT_IDS = [k for k, v in PROMPTS.items() if "{" not in v["ta"].replace("{app}", "")]


@lru_cache(maxsize=4)
def _static_texts(lang: str, app_name: str) -> frozenset[str]:
    return frozenset(PROMPTS[pid][lang].format(app=app_name) for pid in STATIC_PROMPT_IDS)


def is_static_text(t: str, lang: str) -> bool:
    """True if t is a fixed prompt (no user data), so its audio may be cached on disk and shared."""
    return t in _static_texts(lang, get_settings().APP_NAME)


def text(prompt_id: str, lang: str, channel: str = "web", **kw: object) -> str:
    if channel == "phone" and f"PHONE_{prompt_id}" in PROMPTS:
        prompt_id = f"PHONE_{prompt_id}"
    return PROMPTS[prompt_id][lang].format(app=get_settings().APP_NAME, **kw)


def label(field: str, lang: str) -> str:
    return LABELS[field][lang]
