"""Tamil-script, romanised-Tanglish and English lexicon for numbers, banks and dialogue cues.

NOTE FOR REVIEW (native speaker): every entry here should be checked against what Prisma actually
emits (see bench/probe/probe_report.md) and variants added. Keep tables data-only.
"""

from typing import Literal

Kind = Literal["UNIT", "TEEN", "TENS", "HUND", "HUNDRED", "MULT", "FRAC", "DOUBLE", "TRIPLE",
               "CURRENCY", "FILLER", "AND", "ARTICLE"]
Tag = Literal["ta", "roman", "en"]

# value -> surfaces. Combining forms ("-த்து", "-த்தி", "-ற்றி") share the value of the base form.
UNITS_TA: dict[int, list[str]] = {
    0: ["பூஜ்ஜியம்", "பூஜ்யம்", "பூஜியம்", "சைபர்", "ஜீரோ", "சுழியம்"],
    1: ["ஒன்று", "ஒண்ணு", "ஒன்னு", "ஒரு", "ஓர்"],
    2: ["இரண்டு", "ரெண்டு", "இரெண்டு", "ரண்டு"],
    3: ["மூன்று", "மூணு", "மூனு"],
    4: ["நான்கு", "நாலு"],
    5: ["ஐந்து", "அஞ்சு", "ஐஞ்சு", "அஞ்சி", "அந்து"],  # அந்து: Prisma v2.5 output ("இருபத்தந்தாயிரம்")
    6: ["ஆறு"],
    7: ["ஏழு"],
    8: ["எட்டு"],
    9: ["ஒன்பது", "ஒம்பது"],
}
TEENS_TA: dict[int, list[str]] = {
    10: ["பத்து"],
    11: ["பதினொன்று", "பதினொண்ணு", "பதினொன்னு"],
    12: ["பன்னிரண்டு", "பன்னெண்டு", "பன்னிரெண்டு"],
    13: ["பதிமூன்று", "பதின்மூன்று", "பதிமூணு"],
    14: ["பதினான்கு", "பதினாலு"],
    15: ["பதினைந்து", "பதினஞ்சு"],
    16: ["பதினாறு"],
    17: ["பதினேழு"],
    18: ["பதினெட்டு"],
    19: ["பத்தொன்பது", "பத்தொம்பது"],
}
TENS_TA: dict[int, list[str]] = {
    20: ["இருபது", "இருபத்து", "இருபத்தி"],
    30: ["முப்பது", "முப்பத்து", "முப்பத்தி"],
    40: ["நாற்பது", "நாப்பது", "நாற்பத்து", "நாற்பத்தி", "நாப்பத்து", "நாப்பத்தி"],
    50: ["ஐம்பது", "ஐம்பத்து", "ஐம்பத்தி", "அம்பது", "அம்பத்தி"],
    60: ["அறுபது", "அறுபத்து", "அறுபத்தி"],
    70: ["எழுபது", "எழுபத்து", "எழுபத்தி"],
    80: ["எண்பது", "எண்பத்து", "எண்பத்தி"],
    90: ["தொண்ணூறு", "தொன்னூறு", "தொண்ணூற்று", "தொண்ணூற்றி", "தொண்ணூத்து", "தொண்ணூத்தி"],
}
HUNDREDS_TA: dict[int, list[str]] = {
    100: ["நூறு", "நூற்று", "நூற்றி", "நூத்து", "நூத்தி"],
    200: ["இருநூறு", "இருநூற்று", "இருநூற்றி", "இருநூத்தி", "எறநூறு"],
    300: ["முந்நூறு", "முன்னூறு", "முந்நூற்று", "முன்னூற்றி", "முன்னூத்தி"],
    400: ["நானூறு", "நாநூறு", "நானூற்று", "நானூற்றி", "நானூத்தி"],
    500: ["ஐந்நூறு", "ஐநூறு", "அஞ்சுநூறு", "ஐந்நூற்று", "ஐநூற்று", "ஐநூற்றி", "ஐநூத்தி"],
    600: ["அறுநூறு", "அறுநூற்று", "அறுநூற்றி", "அறுநூத்தி"],
    700: ["எழுநூறு", "எழுநூற்று", "எழுநூற்றி", "எழுநூத்தி"],
    800: ["எண்ணூறு", "எண்ணூற்று", "எண்ணூற்றி", "எண்ணூத்தி"],
    900: ["தொள்ளாயிரம்", "தொள்ளாயிரத்து", "தொள்ளாயிரத்தி"],
}
MULTS_TA: dict[int, list[str]] = {
    1000: ["ஆயிரம்", "ஆயிரத்து", "ஆயிரத்தி"],
    100000: ["லட்சம்", "லட்சத்து", "லட்சத்தி", "இலட்சம்", "லட்ஷம்", "லக்ஷம்", "லச்சம்", "லாக்"],
    10000000: ["கோடி", "கோடியே", "கோடியை"],
}
FRACS_TA: dict[float, list[str]] = {0.5: ["அரை"], 0.25: ["கால்"], 0.75: ["முக்கால்"]}

UNITS_ROMAN: dict[int, list[str]] = {
    0: ["poojyam", "poojiyam", "poojjiyam", "pujyam", "saibar", "saipar", "jeero", "ziro"],
    1: ["onru", "onnu", "oru", "ondru", "onu", "ondhu"],
    2: ["irandu", "rendu", "randu", "erandu", "irendu", "rentu"],
    3: ["moonru", "moonu", "munu", "moondru", "moonnu"],
    4: ["naangu", "naalu", "nalu", "naanku", "naangu", "nangu"],
    5: ["ainthu", "aindhu", "anju", "anchu", "ainju", "aynthu", "aidhu"],
    6: ["aaru", "aru"],
    7: ["ezhu", "elu", "yezhu", "ezu", "eazhu"],
    8: ["ettu", "yettu", "eattu"],
    9: ["onbadhu", "onbathu", "ombadhu", "ombathu", "onpathu"],
}
TEENS_ROMAN: dict[int, list[str]] = {
    10: ["pathu", "padhu", "patthu", "paththu"],
    11: ["padhinonnu", "pathinonnu", "padhinonru"],
    12: ["pannendu", "pannirendu", "panirandu", "pannirandu"],
    13: ["padhimoonu", "pathimoonu", "padhimoonru"],
    14: ["padhinaalu", "pathinalu", "padhinaangu", "pathinaalu"],
    15: ["padhinanju", "pathinanju", "padhinainthu"],
    16: ["padhinaaru", "pathinaaru"],
    17: ["padhinezhu", "pathinezhu", "padhinelu"],
    18: ["padhinettu", "pathinettu"],
    19: ["patthombadhu", "pathonbathu", "pathombathu", "patthonbathu"],
}
TENS_ROMAN: dict[int, list[str]] = {
    20: ["irubadhu", "irubathu", "irupathu", "irubathi", "irubadhi", "irupathi", "irubatthu", "irubatthi"],
    30: ["muppadhu", "muppathu", "muppathi", "muppadhi"],
    40: ["naarpadhu", "naarpathu", "naappadhu", "nappathu", "naappathu", "naarpathi", "naappathi"],
    50: ["aimbadhu", "aimbathu", "ambathu", "aimpathu", "ambadhu", "aimbathi", "ambathi", "aimbadhi"],
    60: ["arubadhu", "arubathu", "arupathu", "arubathi"],
    70: ["ezhubadhu", "ezhubathu", "elubathu", "ezhupathu", "ezhubathi"],
    80: ["enbadhu", "enbathu", "enpathu", "enbathi"],
    90: ["thonnooru", "thonnuru", "tonnooru", "thonnuuru", "thonnootthi", "thonnoothi", "thonnutthi"],
}
HUNDREDS_ROMAN: dict[int, list[str]] = {
    100: ["nooru", "nuru", "nuuru", "nootthi", "noothi", "nootri", "nootru"],
    200: ["irunooru", "irunuru", "irunoothi", "irunootthi"],
    300: ["munnooru", "munnuru", "munnoothi"],
    400: ["naanooru", "nanuru", "naanoothi"],
    500: ["ainnooru", "ainooru", "ainuru", "anjunooru", "ainoothi", "ainnoothi"],
    600: ["arunooru", "arunoothi"],
    700: ["ezhunooru", "ezhunoothi"],
    800: ["ennooru", "ennuru", "ennoothi"],
    900: ["thollaayiram", "thollayiram", "thollaayirathu", "thollaayirathi", "thollayirathu", "thollayirathi"],
}
MULTS_ROMAN: dict[int, list[str]] = {
    1000: ["aayiram", "ayiram", "aayram", "aiyiram", "aayirathu", "aayirathi", "ayirathu"],
    100000: ["latcham", "latchathu", "latchathi", "laksham", "lakshath", "lakshathu", "lakshathi", "lacham",
             "latsam", "latchatthi"],
    10000000: ["kodi", "kodiye"],
}
FRACS_ROMAN: dict[float, list[str]] = {0.5: ["arai", "ara"], 0.25: ["kaal"], 0.75: ["mukkaal", "mukal"]}

UNITS_EN: dict[int, list[str]] = {
    0: ["zero"], 1: ["one"], 2: ["two"], 3: ["three"], 4: ["four"], 5: ["five"],
    6: ["six"], 7: ["seven"], 8: ["eight"], 9: ["nine"],
}
TEENS_EN: dict[int, list[str]] = {
    10: ["ten"], 11: ["eleven"], 12: ["twelve"], 13: ["thirteen"], 14: ["fourteen"], 15: ["fifteen"],
    16: ["sixteen"], 17: ["seventeen"], 18: ["eighteen"], 19: ["nineteen"],
}
TENS_EN: dict[int, list[str]] = {
    20: ["twenty"], 30: ["thirty"], 40: ["forty", "fourty"], 50: ["fifty"], 60: ["sixty"],
    70: ["seventy"], 80: ["eighty"], 90: ["ninety"],
}
MULTS_EN: dict[int, list[str]] = {
    1000: ["thousand", "thousands", "k"],
    100000: ["lakh", "lakhs", "lac", "lacs", "lakhs"],
    10000000: ["crore", "crores"],
}
FRACS_EN: dict[float, list[str]] = {0.5: ["half"], 0.25: ["quarter"]}

# English number words as Prisma writes them in Tamil script (probe 2026-11-02: "நைன் எயிட்", "ஃபிஃப்டி தௌசண்ட்").
UNITS_EN_TA: dict[int, list[str]] = {
    0: ["ஸீரோ", "சீரோ"], 1: ["ஒன்"], 2: ["டூ"], 3: ["த்ரீ", "திரீ"], 4: ["ஃபோர்"], 5: ["ஃபைவ்", "பைவ்"],
    6: ["சிக்ஸ்"], 7: ["செவன்"], 8: ["எயிட்", "எய்ட்"], 9: ["நைன்"],
}
TEENS_EN_TA: dict[int, list[str]] = {10: ["டென்"], 11: ["லெவன்", "இலெவன்"], 12: ["ட்வெல்வ்"], 15: ["ஃபிஃப்டீன்"]}
TENS_EN_TA: dict[int, list[str]] = {
    20: ["ட்வென்டி", "ட்வெண்டி"], 30: ["தர்ட்டி", "தர்டி"], 40: ["ஃபார்ட்டி", "ஃபோர்ட்டி"],
    50: ["ஃபிஃப்டி", "பிஃப்டி", "ஃபிப்டி"], 60: ["சிக்ஸ்டி"], 70: ["செவன்டி", "செவன்ட்டி"],
    80: ["எய்ட்டி", "எயிட்டி"], 90: ["நைன்டி", "நைன்ட்டி"],
}
MULTS_EN_TA: dict[int, list[str]] = {
    1000: ["தௌசண்ட்", "தவுசண்ட்", "தவுஸண்ட்"], 100000: ["லேக்", "லேக்ஸ்", "லாக்ஸ்"], 10000000: ["க்ரோர்", "குரோர்"],
}

SPECIAL: dict[str, tuple[Kind, Tag]] = {
    # double / triple
    "டபுள்": ("DOUBLE", "ta"), "டபிள்": ("DOUBLE", "ta"), "double": ("DOUBLE", "en"), "dabul": ("DOUBLE", "roman"),
    "டிரிபிள்": ("TRIPLE", "ta"), "ட்ரிபிள்": ("TRIPLE", "ta"), "triple": ("TRIPLE", "en"),
    "tripple": ("TRIPLE", "en"),
    # currency markers
    "ரூபாய்": ("CURRENCY", "ta"), "ரூபா": ("CURRENCY", "ta"), "ரூவா": ("CURRENCY", "ta"),
    "ரூபாயை": ("CURRENCY", "ta"), "₹": ("CURRENCY", "en"), "rs": ("CURRENCY", "en"), "inr": ("CURRENCY", "en"),
    "rupees": ("CURRENCY", "en"), "rupee": ("CURRENCY", "en"), "rubaa": ("CURRENCY", "roman"),
    "ruba": ("CURRENCY", "roman"), "rooba": ("CURRENCY", "roman"), "roobaa": ("CURRENCY", "roman"),
    "rupaai": ("CURRENCY", "roman"), "rupai": ("CURRENCY", "roman"), "roova": ("CURRENCY", "roman"),
    "ரூ": ("CURRENCY", "ta"), "ருபீஸ்": ("CURRENCY", "en"), "ருப்பீஸ்": ("CURRENCY", "en"),
    "roobai": ("CURRENCY", "roman"), "rubai": ("CURRENCY", "roman"),
    "ஹன்ட்ரட்": ("HUNDRED", "en"), "ஹண்ட்ரட்": ("HUNDRED", "en"),
    # fillers (single filler token is allowed inside a number)
    "அ": ("FILLER", "ta"), "ம்": ("FILLER", "ta"), "ம்ம்": ("FILLER", "ta"), "உம்": ("FILLER", "ta"),
    "ஹ்ம்": ("FILLER", "ta"), "ஆங்": ("FILLER", "ta"), "uh": ("FILLER", "en"), "um": ("FILLER", "en"),
    "umm": ("FILLER", "en"), "hmm": ("FILLER", "en"), "ah": ("FILLER", "en"), "er": ("FILLER", "en"),
    "ok": ("FILLER", "en"), "okay": ("FILLER", "en"), "aa": ("FILLER", "roman"),
    # glue
    "and": ("AND", "en"), "a": ("ARTICLE", "en"), "hundred": ("HUNDRED", "en"), "hundreds": ("HUNDRED", "en"),
}

# Suffixes that may follow a number word ("ஆயிரத்துக்கு", "ettula", "latchamdhaan").
SUFFIXES_TA = ["க்கு", "கு", "தான்", "ல", "லே", "ல்", "உம்", "ஆ", "ஏ", "ஐ", "க்", "ம்"]
SUFFIXES_ROMAN = ["kku", "ku", "thaan", "dhaan", "than", "dhan", "la", "le", "um", "aa", "ae", "e", "u"]

TAMIL_VOWEL_SIGNS = {
    "ா": "ஆ", "ி": "இ", "ீ": "ஈ", "ு": "உ", "ூ": "ஊ", "ெ": "எ", "ே": "ஏ", "ை": "ஐ", "ொ": "ஒ", "ோ": "ஓ", "ௌ": "ஔ",
}
TAMIL_VIRAMA = "்"

DIGIT_WORDS_TA = ["பூஜ்ஜியம்", "ஒன்று", "இரண்டு", "மூன்று", "நான்கு", "ஐந்து", "ஆறு", "ஏழு", "எட்டு", "ஒன்பது"]
DIGIT_WORDS_EN = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]

# ---------------------------------------------------------------- banks
BANK_ALIASES: dict[str, list[str]] = {
    "SBI": ["sbi", "state bank", "எஸ்பிஐ", "எஸ்.பி.ஐ", "ஸ்டேட் பேங்க்", "எஸ் பி ஐ", "s b i",
            # Prisma v2.5 output seen in smoke test 2026-11-02 ("எஸ்பி" alone also means police SP, so require பேங்க்)
            "எஸ் பை", "எஸ்பை", "எஸ்பி பேங்க்", "எஸ் பி பேங்க்"],
    "HDFC": ["hdfc", "எச்டிஎஃப்சி", "ஹெச்டிஎஃப்சி", "எச் டி எஃப் சி", "h d f c"],
    "ICICI": ["icici", "ஐசிஐசிஐ", "ஐ சி ஐ சி ஐ", "i c i c i"],
    "Axis Bank": ["axis", "ஆக்சிஸ்", "ஆக்ஸிஸ்"],
    "Canara Bank": ["canara", "கனரா"],
    "Indian Bank": ["indian bank", "இந்தியன் பேங்க்", "இந்தியன் வங்கி"],
    "Indian Overseas Bank": ["iob", "indian overseas", "ஐஓபி", "இந்தியன் ஓவர்சீஸ்"],
    "Kotak": ["kotak", "கோட்டக்", "கொட்டக்"],
    "Bank of Baroda": ["bank of baroda", "bob", "பரோடா"],
    "PNB": ["pnb", "punjab national", "பஞ்சாப் நேஷனல்"],
    "Union Bank": ["union bank", "யூனியன் பேங்க்"],
    "Karur Vysya Bank": ["kvb", "karur vysya", "கரூர் வைஸ்யா"],
    "City Union Bank": ["cub", "city union", "சிட்டி யூனியன்"],
    "Tamilnad Mercantile Bank": ["tmb", "tamilnad mercantile", "தமிழ்நாடு மெர்கன்டைல்"],
    "IndusInd": ["indusind", "இண்டஸ்இண்ட்"],
    "Yes Bank": ["yes bank", "யெஸ் பேங்க்"],
    "Federal Bank": ["federal bank", "ஃபெடரல் பேங்க்"],
    "Paytm Payments Bank": ["paytm", "பேடிஎம்"],
    "PhonePe": ["phonepe", "phone pe", "போன்பே", "ஃபோன்பே"],
    "Google Pay": ["gpay", "google pay", "ஜிபே", "கூகுள் பே"],
}
# Tamil-script single words safe for Prisma v2.5 bias_list (letters only, single word).
BANK_ALIASES_TA_SCRIPT = ["எஸ்பிஐ", "எச்டிஎஃப்சி", "ஐசிஐசிஐ", "ஆக்சிஸ்", "கனரா", "ஐஓபி", "கோட்டக்", "பேடிஎம்",
                          "போன்பே", "ஜிபே", "யுபிஐ", "ஓடிபி"]

# ---------------------------------------------------------------- extractor cues
FRAUD_CUES: dict[str, list[str]] = {
    "OTP_BANK_CALL": ["otp", "ஓடிபி", "kyc", "கேஒய்சி", "card block", "கார்டு பிளாக்", "account block",
                      "bank la irundhu", "பேங்க்ல இருந்து", "atm card", "credit card", "debit card"],
    "UPI_COLLECT": ["collect request", "request vandhuchu", "pin pottaen", "pin potten", "upi pin",
                    "qr code", "scan pannunen", "கலெக்ட்", "க்யூஆர்"],
    "DIGITAL_ARREST": ["digital arrest", "cbi", "customs", "police video call", "arrest warrant", "parcel",
                       "drugs", "டிஜிட்டல் அரெஸ்ட்", "போலீஸ்", "கஸ்டம்ஸ்", "பார்சல்"],
    "INVESTMENT": ["investment", "trading", "stock", "share market", "crypto", "double aagum", "profit",
                   "முதலீடு", "டிரேடிங்", "இன்வெஸ்ட்மென்ட்"],
    "JOB_TASK": ["part time", "task", "youtube like", "rating", "work from home", "job", "வேலை", "டாஸ்க்"],
    "LOAN_APP": ["loan app", "instant loan", "loan", "லோன்", "கடன்"],
    "FAKE_CUSTOMER_CARE": ["customer care", "refund", "helpline", "anydesk", "teamviewer", "screen share",
                           "கஸ்டமர் கேர்", "ரீஃபண்ட்"],
}
AMOUNT_CUES = ["போச்சு", "pochu", "poche", "அனுப்பினேன்", "anuppinen", "anuppunen", "debit", "debited",
               "ரூபாய்", "rubaa", "rupees", "cut aachu", "cut", "கட்", "எடுத்துட்டாங்க", "eduthuttanga",
               "lost", "sent", "paid", "transfer", "டெபிட்", "rs", "₹"]
SUSPECT_PHONE_CUES = ["call vandhuchu", "கால் வந்துச்சு", "number la irundhu", "நம்பர்ல இருந்து", "அந்த நம்பர்",
                      "andha number", "avan number", "அவன் நம்பர்", "called from", "call came", "from number",
                      "phone pannanga", "போன் பண்ணாங்க", "call", "கால்"]
VICTIM_PHONE_CUES = ["en", "என்", "ennoda", "என்னோட", "my", "enakku"]
DATE_CUES = {
    "today": ["இன்னைக்கு", "இன்று", "innaikku", "innikki", "today"],
    "yesterday": ["நேத்து", "நேற்று", "nethu", "netthu", "yesterday"],
}
TIME_CUES = ["மணி", "mani", "o'clock", "oclock", "am", "pm", "காலை", "kaalai", "மதியம்", "madhiyam",
             "சாயங்காலம்", "saayangalam", "evening", "morning", "night", "ராத்திரி", "raathiri"]

# ---------------------------------------------------------------- Tamil Nadu districts (38)
DISTRICTS: dict[str, list[str]] = {
    "Ariyalur": ["ariyalur", "அரியலூர்"], "Chengalpattu": ["chengalpattu", "செங்கல்பட்டு"],
    "Chennai": ["chennai", "madras", "சென்னை"], "Coimbatore": ["coimbatore", "kovai", "கோயம்புத்தூர்", "கோவை"],
    "Cuddalore": ["cuddalore", "கடலூர்"], "Dharmapuri": ["dharmapuri", "தர்மபுரி"],
    "Dindigul": ["dindigul", "திண்டுக்கல்"], "Erode": ["erode", "ஈரோடு"],
    "Kallakurichi": ["kallakurichi", "கள்ளக்குறிச்சி"], "Kancheepuram": ["kancheepuram", "kanchipuram", "காஞ்சிபுரம்"],
    "Kanniyakumari": ["kanniyakumari", "kanyakumari", "nagercoil", "கன்னியாகுமரி", "நாகர்கோவில்"],
    "Karur": ["karur", "கரூர்"], "Krishnagiri": ["krishnagiri", "கிருஷ்ணகிரி"], "Madurai": ["madurai", "மதுரை"],
    "Mayiladuthurai": ["mayiladuthurai", "மயிலாடுதுறை"], "Nagapattinam": ["nagapattinam", "நாகப்பட்டினம்"],
    "Namakkal": ["namakkal", "நாமக்கல்"], "Nilgiris": ["nilgiris", "ooty", "நீலகிரி", "ஊட்டி"],
    "Perambalur": ["perambalur", "பெரம்பலூர்"], "Pudukkottai": ["pudukkottai", "pudukottai", "புதுக்கோட்டை"],
    "Ramanathapuram": ["ramanathapuram", "ramnad", "ராமநாதபுரம்"], "Ranipet": ["ranipet", "ராணிப்பேட்டை"],
    "Salem": ["salem", "சேலம்"], "Sivaganga": ["sivaganga", "sivagangai", "சிவகங்கை"],
    "Tenkasi": ["tenkasi", "தென்காசி"], "Thanjavur": ["thanjavur", "tanjore", "தஞ்சாவூர்", "தஞ்சை"],
    "Theni": ["theni", "தேனி"], "Thoothukudi": ["thoothukudi", "tuticorin", "தூத்துக்குடி"],
    "Tiruchirappalli": ["tiruchirappalli", "trichy", "tiruchi", "திருச்சி", "திருச்சிராப்பள்ளி"],
    "Tirunelveli": ["tirunelveli", "nellai", "திருநெல்வேலி", "நெல்லை"], "Tirupathur": ["tirupathur", "திருப்பத்தூர்"],
    "Tiruppur": ["tiruppur", "tirupur", "திருப்பூர்"], "Tiruvallur": ["tiruvallur", "thiruvallur", "திருவள்ளூர்"],
    "Tiruvannamalai": ["tiruvannamalai", "திருவண்ணாமலை"], "Tiruvarur": ["tiruvarur", "திருவாரூர்"],
    "Vellore": ["vellore", "வேலூர்"], "Viluppuram": ["viluppuram", "villupuram", "விழுப்புரம்"],
    "Virudhunagar": ["virudhunagar", "விருதுநகர்"],
}
TIME_OF_DAY = {
    "morning": ["காலை", "kaalai", "kalai", "morning", "am"],
    "afternoon": ["மதியம்", "madhiyam", "mathiyam", "afternoon"],
    "evening": ["சாயங்காலம்", "மாலை", "saayangalam", "saayankaalam", "maalai", "evening", "pm"],
    "night": ["ராத்திரி", "இரவு", "raathiri", "rathiri", "iravu", "night"],
}
DAYS_AGO_CUES = ["நாள் முன்னாடி", "நாளைக்கு முன்னாடி", "naal munnadi", "days ago", "day ago", "naalaikku munnadi"]

# ---------------------------------------------------------------- time expressions
# checked BEFORE "yesterday": "முந்தாநேத்து" contains "நேத்து"
DAY_BEFORE_CUES = ["முந்தாநேத்து", "முந்தா நேத்து", "முந்தைய நாள்", "munthanethu", "mundhanethu", "munthaa nethu",
                   "day before yesterday"]
HOURS_AGO_CUES = ["மணி நேரம் முன்னாடி", "மணி நேரத்துக்கு முன்னாடி", "மணிநேரம் முன்பு", "மணி நேரம் முன்பு",
                  "mani neram munnadi", "mani nerathukku munnadi", "hours ago", "hour ago", "hrs ago"]
MINUTES_AGO_CUES = ["நிமிஷம் முன்னாடி", "நிமிடம் முன்பு", "நிமிஷத்துக்கு முன்னாடி", "nimisham munnadi",
                    "nimishathukku munnadi", "minutes ago", "minute ago", "mins ago"]
JUST_NOW_CUES = ["இப்போ தான்", "இப்பதான்", "இப்போதான்", "இப்ப தான்", "ippo dhaan", "ippo than", "ippa dhan",
                 "ippadhan", "just now", "கொஞ்ச நேரம் முன்னாடி", "konja neram munnadi", "few minutes back"]
MANI_CUES = ["மணி", "மணிக்கு", "மணிக்கா", "மணியளவில்", "மணிக்குள்ள", "mani", "maniku", "manikku", "manikki",
             "maniyalavil", "o'clock", "oclock", "pm", "am", "p.m", "a.m"]
MONTHS: dict[int, list[str]] = {
    1: ["ஜனவரி", "january", "jan"], 2: ["பிப்ரவரி", "february", "feb"], 3: ["மார்ச்", "march", "mar"],
    4: ["ஏப்ரல்", "april", "apr"], 5: ["மே", "may"], 6: ["ஜூன்", "june", "jun"], 7: ["ஜூலை", "july", "jul"],
    8: ["ஆகஸ்ட்", "ஆகஸ்டு", "august", "aug"], 9: ["செப்டம்பர்", "september", "sep", "sept"],
    10: ["அக்டோபர்", "october", "oct"], 11: ["நவம்பர்", "november", "nov"], 12: ["டிசம்பர்", "december", "dec"],
}
MONTH_NAMES_TA = ["", "ஜனவரி", "பிப்ரவரி", "மார்ச்", "ஏப்ரல்", "மே", "ஜூன்", "ஜூலை", "ஆகஸ்ட்", "செப்டம்பர்",
                  "அக்டோபர்", "நவம்பர்", "டிசம்பர்"]

# relative-time phrasings seen in role-play ("rendu mani neram aachu", "12 minutes munnadi")
HOURS_AGO_CUES += ["mani neram aachu", "mani neram achu", "மணி நேரம் ஆச்சு", "மணிநேரம் ஆச்சு", "hours munnadi",
                   "hour munnadi", "mani nerathuku munnadi"]
MINUTES_AGO_CUES += ["minutes munnadi", "minute munnadi", "mins munnadi", "nimisham aachu", "நிமிஷம் ஆச்சு",
                     "நிமிடம் முன்னாடி", "nimishathuku munnadi"]
TIME_OF_DAY["morning"] += ["kaalaila", "காலையில", "காலையில்"]
TIME_OF_DAY["afternoon"] += ["madhiyaanam", "மத்தியானம்", "noon"]
TIME_OF_DAY["evening"] += ["saayangaalam", "sayangalam", "saayangaalathula"]
TIME_OF_DAY["night"] += ["raathiriyila", "ராத்திரியில", "nightla"]
DAY_BEFORE_CUES += ["munnaal", "mundhaanethu", "mundhaa nethu"]
JUST_NOW_CUES += ["ippo thaan", "ippo dhan", "ippothaan", "ippa thaan"]
TOMORROW_CUES = ["நாளைக்கு", "நாளை", "naalaikku", "naalai", "nalaiku", "tomorrow"]

# ---------------------------------------------------------------- multi-transaction narrative
TOTAL_CUES = ["total", "மொத்தம்", "மொத்தமா", "mothham", "motham", "mothama", "mottham", "altogether", "overall"]
# cue -> expected number of transactions (None = "more than one", count unknown)
MULTI_TXN_CUES: dict[str, int | None] = {
    "rendu thadava": 2, "rendu thadavai": 2, "ரெண்டு தடவை": 2, "இரண்டு தடவை": 2, "two times": 2, "twice": 2,
    "rendu transaction": 2, "2 transaction": 2, "two transactions": 2, "ரெண்டு transaction": 2,
    "moonu thadava": 3, "moonu thadavai": 3, "மூணு தடவை": 3, "three times": 3, "moonu transaction": 3,
    "3 transaction": 3, "three transactions": 3, "மூணு transaction": 3,
    "naalu thadava": 4, "நாலு தடவை": 4, "four times": 4,
    "innoru": None, "இன்னொரு": None, "again": None, "marupadiyum": None, "மறுபடியும்": None, "thirumbavum": None,
    "திரும்பவும்": None, "another": None,
}
PAYMENT_MODES: dict[str, list[str]] = {
    "UPI": ["upi", "gpay", "google pay", "phonepe", "phone pe", "paytm", "bhim", "qr", "யுபிஐ", "ஜிபே", "போன்பே"],
    "IMPS": ["imps"],
    "NEFT": ["neft", "rtgs"],
    "Card": ["card", "debit card", "credit card", "கார்டு", "கார்ட்", "கார்டில்", "atm"],
    "Net banking": ["net banking", "netbanking", "internet banking", "நெட் பேங்கிங்"],
    "Wallet": ["wallet", "வாலட்"],
}
# "UPI illa, card" / "not by UPI": a payment word next to one of these was ruled out, not named
PAYMENT_NEGATED_AFTER = {"illa", "illai", "illae", "alla", "இல்ல", "இல்லை", "இல்லே", "அல்ல"}
PAYMENT_NEGATED_BEFORE = {"not"}
PAYMENT_NEGATION_LINKS = {"by", "via", "through", "using"}
