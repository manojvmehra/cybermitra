"""Every spoken / shown prompt, keyed by id, in Tamil and English. {app} is APP_NAME.

NEXT_STEPS lines (NS_*) are victim guidance. Each needs an official source in docs/NEXT_STEPS_SOURCES.md;
NEXT_STEPS_SOURCED lists the ones that have one. The rest carry a "draft guidance" tag in DEMO_MODE."""

from functools import lru_cache

from app.config import get_settings

PROMPTS: dict[str, dict[str, str]] = {
    # The caller has dialled 1930 and the AI takes the call. The keys come first, so every later question can
    # just say "type it". Then one question for the whole story, so most calls need only a check after it.
    "OPENING": {
        "ta": "1930 சைபர் கிரைம் உதவி எண்ணுக்கு வணக்கம். நான் {app}, AI உதவியாளர். "
              "ஆமான்னா ஒன்று, இல்லைன்னா இரண்டு, புரியலைன்னா மூணு. நம்பர் டைப் பண்ண ஸ்டார், டைப், அப்புறம் ஹாஷ். "
              "என்ன நடந்தது, எப்போ, எவ்வளவு பணம் போச்சு, UPI-யா கார்டா நெட் பேங்கிங்கா, எந்த பேங்க், "
              "எல்லாத்தையும் ஒரே தடவையா சொல்லுங்க.",
        "en": "Welcome to the 1930 cyber crime helpline. I am {app}, the AI assistant. "
              "Press 1 for yes, 2 for no, and 3 if you did not understand. To type a number, press star, type it, "
              "then hash. Tell me everything in one go: what happened, when, how much money went, "
              "how it was paid, UPI, card or net banking, and from which bank.",
    },
    "STORY_CHECK": {"ta": "நான் புரிஞ்சுக்கிட்டது: {facts}. சரியா?",
                    "en": "Let me check: {facts}. Is that right?"},
    "STORY_ONE_BY_ONE": {"ta": "சரி, ஒவ்வொன்றா சரிபார்க்கலாம்.", "en": "Okay, let's check them one by one."},
    "FACT_payment_mode": {"ta": "{v} மூலமா", "en": "by {v}"},
    "FACT_victim_bank": {"ta": "{v} அக்கவுண்ட்ல இருந்து", "en": "from your {v} account"},
    "NO_FACTS": {"ta": "உங்க புகார்", "en": "your complaint"},
    "ASK_STORY": {"ta": "என்ன நடந்தது, சொல்லுங்க.", "en": "Tell me what happened."},
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
    # UTR and mobile numbers are typed, never asked aloud: the keypad is exact, speech is not.
    "ASK_utr": {
        "ta": "பேங்க் SMS-ல உள்ள பன்னிரண்டு இலக்க UTR நம்பர்: ஸ்டார் அழுத்தி, டைப் பண்ணி, ஹாஷ் அழுத்துங்க. "
              "தெரியலைன்னா இரண்டு அழுத்துங்க.",
        "en": "The 12-digit UTR number from the bank SMS: press star, type it, then press hash. "
              "If you don't have it, press 2.",
    },
    "ASK_suspect_phone": {"ta": "உங்களுக்கு கால் வந்த நம்பர்: ஸ்டார் அழுத்தி, டைப் பண்ணி, ஹாஷ் அழுத்துங்க. "
                                "தெரியலைன்னா இரண்டு அழுத்துங்க.",
                          "en": "The number the fraudster called from: press star, type it, then press hash. "
                                "If you don't know it, press 2."},
    "ASK_suspect_upi": {
        "ta": "பணம் அனுப்பின UPI ஐடி தெரியுமா? தெரியலைன்னா 'தெரியல' என்று சொல்லுங்கள்.",
        "en": "Do you know the UPI ID the money went to? If not, say 'don't know'.",
    },
    "ASK_victim_name": {"ta": "உங்கள் பெயர் என்ன?", "en": "What is your name?"},
    "ASK_victim_mobile": {"ta": "உங்க மொபைல் நம்பர்: ஸ்டார் அழுத்தி, டைப் பண்ணி, ஹாஷ் அழுத்துங்க.",
                          "en": "Your mobile number: press star, type it, then press hash."},
    "ASK_district": {"ta": "நீங்கள் எந்த மாவட்டம்?", "en": "Which district are you in?"},
    "DIDNT_CATCH": {"ta": "மன்னிக்கவும், சரியா புரியல. மறுபடி சொல்லுங்க.",
                    "en": "Sorry, I didn't catch that. Please say it again."},
    "TYPE_amount": {"ta": "மன்னிக்கவும், தொகை சரியா புரியல. ஸ்டார் அழுத்தி, தொகையை ரூபாயில் டைப் பண்ணி, ஹாஷ் அழுத்துங்க.",
                    "en": "Sorry, I didn't catch the amount. Press star, type the amount in rupees, then press hash."},
    "SILENCE": {"ta": "எதுவும் கேட்கல. தயவு செய்து பேசுங்க.", "en": "I didn't hear anything. Please speak now."},
    "WRONG_LEN_utr": {"ta": "எனக்கு {n} இலக்கம் வந்தது. UTR பன்னிரண்டு இலக்கம். ஸ்டார் அழுத்தி, மறுபடி டைப் பண்ணி, ஹாஷ் அழுத்துங்க.",
                      "en": "I got {n} digits. A UTR has 12. Press star, type it again, then press hash."},
    "WRONG_LEN_phone": {"ta": "எனக்கு {n} இலக்கம் வந்தது. மொபைல் நம்பர் பத்து இலக்கம். ஸ்டார் அழுத்தி, மறுபடி டைப் பண்ணி, ஹாஷ் அழுத்துங்க.",
                        "en": "I got {n} digits. A mobile number has 10. Press star, type it again, then press hash."},
    "BAD_PHONE": {"ta": "மொபைல் நம்பர் ஆறு, ஏழு, எட்டு அல்லது ஒன்பதில் தொடங்கும். ஸ்டார் அழுத்தி, மறுபடி டைப் பண்ணி, ஹாஷ் அழுத்துங்க.",
                  "en": "A mobile number starts with 6, 7, 8 or 9. Press star, type it again, then press hash."},
    "CORRECT_CHUNK": {"ta": "சரியான இலக்கங்களை சொல்லுங்க, அல்லது ஸ்டார் அழுத்தி, டைப் பண்ணி, ஹாஷ் அழுத்துங்க.",
                      "en": "Please say the correct digits, or press star, type them, then press hash."},
    "CONFIRM_HINT": {"ta": "சரி என்றால் ஒன்று, தப்பு என்றால் இரண்டு அழுத்துங்க.",
                     "en": "Press 1 if it is right, or 2 if it is wrong."},
    "USE_NUMPAD": {"ta": "ஸ்டார் அழுத்தி, டைப் பண்ணி, ஹாஷ் அழுத்துங்க. தெரியலைன்னா இரண்டு.",
                   "en": "Press star, type it, then press hash. If you don't know it, press 2."},
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
               "en": "Transactions: {n}, total {total}. Is everything correct?"},
    "REVIEW_FIX": {"ta": "ஏதாவது தப்புன்னா, அதிகாரியிடம் பேச பூஜ்ஜியம் அழுத்துங்க. அப்படியே அனுப்ப ஒன்று அழுத்துங்க.",
                   "en": "If something is wrong, press 0 for an officer. To send it as it is, press 1."},
    # The last thing said: a summary, the SMS, goodbye. The call then ends by itself.
    "QUEUED": {"ta": "நன்றி. {facts}, இதை பதிவு செஞ்சிருக்கேன். ஒரு அதிகாரி சரிபார்ப்பார். "
                     "குறிப்பு எண்ணும் அடுத்து செய்ய வேண்டியதும் SMS-ல அனுப்புவோம். வணக்கம்.",
               "en": "Thank you. I have noted {facts}. An officer will review your complaint. "
                     "We will send you an SMS with your reference number and next steps. Goodbye."},
    "NS_CALL_BANK": {"ta": "உடனே உங்க பேங்க் ஹெல்ப்லைனுக்கு கால் பண்ணி மோசடியை சொல்லி, கார்டு, UPI-ஐ பிளாக் பண்ண சொல்லுங்க.",
                     "en": "Call your bank's helpline now, report the fraud, and ask them to block your card and UPI."},
    "NS_KEEP_EVIDENCE": {"ta": "SMS, கால் லிஸ்ட், சாட் எதையும் அழிக்காதீங்க. ஸ்கிரீன்ஷாட் எடுத்து வெச்சுக்கோங்க.",
                         "en": "Do not delete SMS, call logs or chats. Take screenshots."},
    "NS_CHANGE_PIN": {"ta": "உங்க சொந்த போனிலிருந்து நெட் பேங்கிங், UPI PIN-ஐ மாத்துங்க.",
                      "en": "Change your net-banking password and UPI PIN from your own phone."},
    "NS_RECOVERY_SCAM": {"ta": "பணத்தை திரும்ப வாங்கித் தர்றோம்னு கட்டணம் கேட்கறவங்க இன்னொரு மோசடி.",
                         "en": "Anyone who offers to recover your money for a fee is another scam."},
    "HANDOFF_HUMAN": {"ta": "லைன்லயே இருங்க, உங்களை ஒரு அதிகாரியிடம் இணைக்கிறேன் (டெமோவில் இது மாதிரி மட்டும்). "
                            "நீங்க சொன்னது அவருக்குத் தெரியும்.",
                      "en": "Please stay on the line, I am connecting you to an officer (simulated in demo). "
                            "They will have everything you told me."},
    "HANDOFF_NONFIN": {"ta": "இதற்கு ஒரு அதிகாரி உதவுவார், லைன்லயே இருங்க. cybercrime.gov.in-லும் புகார் கொடுக்கலாம். "
                             "நீங்கள் தனியாக இல்லை.",
                       "en": "An officer will help with this, please stay on the line. You can also report at "
                             "cybercrime.gov.in. You are not alone."},
    "HANDOFF_WELLBEING": {"ta": "நீங்கள் முக்கியம். இப்போதே Tele-MANAS 14416-க்கு கால் பண்ணுங்க. ஒரு அதிகாரியையும் இணைக்கிறேன்.",
                          "en": "You matter. Please call Tele-MANAS on 14416 now. I am also connecting you to an officer."},
    "RATE_LIMITED": {"ta": "எல்லா லைன்களும் இப்போது பிஸியாக உள்ளன. சில நிமிடங்களில் மறுபடி கால் பண்ணுங்க.",
                     "en": "All our lines are busy right now. Please call again in a few minutes."},
    "TOO_LONG": {"ta": "கொஞ்சம் சுருக்கமா சொல்லுங்க.", "en": "Please keep it shorter."},

    # Telephony has no screen. text() prefers PHONE_<id> over <id> on that channel.
    "PHONE_OPENING": {
        "ta": "1930 சைபர் கிரைம் உதவி எண்ணுக்கு வணக்கம். இது சோதனை டெமோ, உண்மையான விவரங்கள் வேண்டாம். நான் {app}, AI உதவியாளர். "
              "ஆமான்னா ஒன்று, இல்லைன்னா இரண்டு, புரியலைன்னா மூணு. நம்பர் டைப் பண்ண ஸ்டார், டைப், அப்புறம் ஹாஷ். "
              "என்ன நடந்தது, எப்போ, எவ்வளவு பணம் போச்சு, UPI-யா கார்டா நெட் பேங்கிங்கா, எந்த பேங்க், "
              "எல்லாத்தையும் ஒரே தடவையா சொல்லுங்க.",
        "en": "Welcome to the 1930 cyber crime helpline. This is an experimental demo, so give no real details. "
              "I am {app}, the AI assistant. Press 1 for yes, 2 for no, and 3 if you did not understand. "
              "To type a number, press star, type it, then hash. Tell me everything in one go: what happened, when, how much money went, "
              "how it was paid, UPI, card or net banking, and from which bank.",
    },
    "PHONE_HIGH_AMOUNT": {"ta": "இது பத்து லட்சத்துக்கு மேல். தொகையை கவனமா கேட்டு சரிபாருங்க.",
                          "en": "This is above ten lakh. Please listen carefully and check the amount."},
    "PHONE_QUEUED": {"ta": "நன்றி. {facts}, இதை பதிவு செஞ்சிருக்கேன். ஒரு அதிகாரி சரிபார்ப்பார். "
                           "இந்த சோதனை டெமோவில் SMS அனுப்பப்படாது, அதனால் குறிப்பு எண்ணை குறிச்சுக்கோங்க.",
                     "en": "Thank you. I have noted {facts}. An officer will review your complaint. "
                           "This experimental demo sends no SMS, so please note your draft reference."},
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

# The caller is already on 1930, so the steps start with their bank.
NEXT_STEPS = ["NS_CALL_BANK", "NS_KEEP_EVIDENCE", "NS_CHANGE_PIN", "NS_RECOVERY_SCAM"]
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
