"""Deterministic number parsing for Tamil script, romanised Tanglish, English words and ITN digits.

No language model is involved. Words are segmented with a memoised longest-match search over a
stem table that understands Tamil sandhi (ஐம்பது+ஆயிரம் -> ஐம்பதாயிரம்) and the romanised equivalent
(aimbadhu+aayiram -> aimbadhaayiram). Amounts follow Indian grammar:
(a×1e7) + (b×1e5) + (c×1000) + (d×100) + e.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal, cast

from app.nlp import lexicon_ta as L

Method = Literal["itn_digits", "tamil_words", "roman_words", "english_words", "mixed", "none"]
VALUE_KINDS = {"UNIT", "TEEN", "TENS", "HUND", "HUNDRED", "MULT", "FRAC", "NUM"}
SEGMENTABLE_KINDS = {"UNIT", "TEEN", "TENS", "HUND", "MULT", "FRAC"}
_TAMIL_DIGITS = str.maketrans("௦௧௨௩௪௫௬௭௮௯", "0123456789")


# ------------------------------------------------------------------ data types
@dataclass(frozen=True)
class Entry:
    kind: str
    value: float
    tag: str


@dataclass
class Tok:
    kind: str
    value: float = 0
    tag: str = ""
    word: int = 0
    text: str = ""
    ambiguous: bool = False


@dataclass
class Span:
    start: int  # word index, inclusive
    end: int  # word index, exclusive
    text: str
    tokens: list[Tok]
    amount: int | None = None
    amount_strong: bool = False
    digits: str = ""
    has_currency: bool = False
    has_mult: bool = False
    method: Method = "none"


@dataclass
class ParseResult:
    value: int | str | None
    spans: list[Span] = field(default_factory=list)
    method: Method = "none"
    warnings: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ lexicon build
def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _build() -> tuple[dict[str, Entry], dict[str, Entry], dict[str, list[Entry]]]:
    seg: dict[str, Entry] = {}

    def add(table: dict[Any, list[str]], kind: str, tag: str) -> None:
        for value, surfaces in table.items():
            for s in surfaces:
                seg.setdefault(_nfc(s).lower(), Entry(kind, value, tag))

    add(L.UNITS_TA, "UNIT", "ta")
    add(L.TEENS_TA, "TEEN", "ta")
    add(L.TENS_TA, "TENS", "ta")
    add(L.HUNDREDS_TA, "HUND", "ta")
    add(L.MULTS_TA, "MULT", "ta")
    add(L.FRACS_TA, "FRAC", "ta")
    add(L.UNITS_ROMAN, "UNIT", "roman")
    add(L.TEENS_ROMAN, "TEEN", "roman")
    add(L.TENS_ROMAN, "TENS", "roman")
    add(L.HUNDREDS_ROMAN, "HUND", "roman")
    add(L.MULTS_ROMAN, "MULT", "roman")
    add(L.FRACS_ROMAN, "FRAC", "roman")
    add(L.UNITS_EN, "UNIT", "en")
    add(L.TEENS_EN, "TEEN", "en")
    add(L.TENS_EN, "TENS", "en")
    add(L.MULTS_EN, "MULT", "en")
    add(L.FRACS_EN, "FRAC", "en")
    add(L.UNITS_EN_TA, "UNIT", "en")
    add(L.TEENS_EN_TA, "TEEN", "en")
    add(L.TENS_EN_TA, "TENS", "en")
    add(L.MULTS_EN_TA, "MULT", "en")
    # one-letter "k" must only match a whole word ("50k" is split by the word regex)
    whole: dict[str, Entry] = {"k": seg.pop("k")}
    for s, (kind, tag) in L.SPECIAL.items():
        whole[_nfc(s).lower()] = Entry(kind, 0, tag)
    # prefixes for sandhi: words ending in ு (Tamil) / u (roman) drop it before a vowel;
    # words ending in virama fuse with a following vowel sign.
    fuse: dict[str, list[Entry]] = {}
    for s, e in seg.items():
        if s.endswith("ு") or s.endswith(L.TAMIL_VIRAMA) or (e.tag != "ta" and s.endswith("u")):
            fuse.setdefault(s[:-1], []).append(e)
    return seg, whole, fuse


SEG, WHOLE, FUSE = _build()
_MAXLEN = max(len(s) for s in SEG)
_SUFFIX_TA = {_nfc(s) for s in L.SUFFIXES_TA}
_SUFFIX_ROMAN = set(L.SUFFIXES_ROMAN)
_CURRENCY = {s for s, e in WHOLE.items() if e.kind == "CURRENCY"}


def _is_tamil(s: str) -> bool:
    return any("஀" <= ch <= "௿" for ch in s)


# ------------------------------------------------------------------ normalisation + words
def normalise_text(s: str) -> str:
    """NFC, Tamil digits -> ASCII, lowercase Latin, strip punctuation except ₹ , . @, collapse spaces."""
    s = _nfc(s).translate(_TAMIL_DIGITS)
    out = []
    for ch in s:
        cat = unicodedata.category(ch)
        if ch in "₹,.@" or cat[0] in ("L", "M", "N"):
            out.append(ch.lower() if ch.isascii() else ch)
        elif ch == "_":
            out.append(ch)
        else:
            out.append(" ")
    return re.sub(r"\s+", " ", "".join(out)).strip()


_WORD_RE = re.compile(r"[\w.\-]+@[\w.\-]+|₹|\d[\d,]*(?:\.\d+)?|[^\s\d,.₹@]+")


def words(s: str) -> list[str]:
    ws = []
    for w in _WORD_RE.findall(normalise_text(s)):
        w = w.rstrip(",.")
        if w:
            ws.append(w)
    return ws


# ------------------------------------------------------------------ segmentation
def _allow_suffix(e: Entry) -> bool:
    return e.kind in SEGMENTABLE_KINDS


@lru_cache(maxsize=20000)
def _segment(w: str) -> tuple[tuple[Entry, ...], ...] | None:
    """All minimal-length full segmentations of w into number entries (optionally + case suffix)."""
    if not w:
        return ((),)
    tamil = _is_tamil(w)
    suffixes = _SUFFIX_TA if tamil else _SUFFIX_ROMAN
    found: list[tuple[Entry, ...]] = []

    for k in range(min(len(w), _MAXLEN), 0, -1):
        e = SEG.get(w[:k])
        if e is None:
            continue
        rest = w[k:]
        if not rest:
            found.append((e,))
            continue
        if rest in suffixes and _allow_suffix(e):
            found.append((e,))
        sub = _segment(rest)
        if sub:
            found.extend((e, *s) for s in sub)

    for k in range(1, min(len(w), _MAXLEN)):
        entries = FUSE.get(w[:k])
        if not entries:
            continue
        rest = w[k:]
        if tamil:
            if rest[0] == L.TAMIL_VIRAMA:
                continue
            virt = L.TAMIL_VOWEL_SIGNS[rest[0]] + rest[1:] if rest[0] in L.TAMIL_VOWEL_SIGNS else "அ" + rest
        else:
            if rest[0] not in "aeiou":
                continue
            virt = rest
        for e in entries:
            if virt in suffixes and e.value >= 10:
                found.append((e,))
            sub = _segment(virt)
            if sub:
                found.extend((e, *s) for s in sub if s)

    if not found:
        return None
    best = min(len(f) for f in found)
    uniq: dict[tuple[tuple[str, float], ...], tuple[Entry, ...]] = {}
    for f in found:
        if len(f) == best:
            uniq.setdefault(tuple((e.kind, e.value) for e in f), f)
    return tuple(uniq.values())


def tokenize(s: str) -> tuple[list[str], list[Tok]]:
    ws = words(s)
    toks: list[Tok] = []
    for i, w in enumerate(ws):
        if re.fullmatch(r"\d[\d,]*(?:\.\d+)?", w):
            clean = w.replace(",", "")
            val = float(clean) if "." in clean else int(clean)
            toks.append(Tok("NUM", val, "digit", i, clean))
            continue
        if w in WHOLE:
            e = WHOLE[w]
            toks.append(Tok(e.kind, e.value, e.tag, i, w))
            continue
        cur = next((c for c in _CURRENCY if w.startswith(c) and w[len(c):] in (_SUFFIX_TA | _SUFFIX_ROMAN)), None)
        if cur:
            toks.append(Tok("CURRENCY", 0, WHOLE[cur].tag, i, w))
            continue
        segs = _segment(w)
        if not segs:
            toks.append(Tok("WORD", 0, "", i, w))
            continue
        amb = len(segs) > 1
        for e in segs[0]:
            toks.append(Tok(e.kind, e.value, e.tag, i, w, ambiguous=amb))
    return ws, toks


# ------------------------------------------------------------------ spans
def _method(toks: list[Tok]) -> Method:
    tags = {t.tag for t in toks if t.kind in VALUE_KINDS}
    if not tags:
        return "none"
    if len(tags) > 1:
        return "mixed"
    names = {"digit": "itn_digits", "ta": "tamil_words", "roman": "roman_words", "en": "english_words"}
    return cast(Method, names[tags.pop()])


_GROUPED = re.compile(r"₹?\d{1,3}(?:,\d{2,3})+(?:\.\d+)?")


def _group_spans(ws: list[str], toks: list[Tok]) -> list[Span]:
    by_word: dict[int, list[Tok]] = {}
    for t in toks:
        by_word.setdefault(t.word, []).append(t)
    spans: list[Span] = []
    cur: list[int] = []
    gap = 0

    def close() -> None:
        if cur:
            st = [t for i in cur for t in by_word[i]]
            if any(t.kind in VALUE_KINDS for t in st):
                spans.append(Span(cur[0], cur[-1] + 1, " ".join(ws[cur[0]:cur[-1] + 1]), st))
        cur.clear()

    for i in range(len(ws)):
        kinds = {t.kind for t in by_word.get(i, [])}
        if "WORD" in kinds or not kinds:
            close()
            gap = 0
            continue
        if kinds <= {"FILLER", "AND"}:
            if cur:
                gap += 1
                if gap > 1:
                    close()
                    gap = 0
            continue
        if cur and gap > 1:
            close()
        # "40,000 and 10,000": a comma-grouped figure is a whole amount, never the tail of another number
        if cur and _GROUPED.fullmatch(ws[i]) and any(t.kind == "NUM" for j in cur for t in by_word[j]):
            close()
        trailing_unit = "CURRENCY" in kinds and any(t.kind in VALUE_KINDS for j in cur for t in by_word[j])
        cur.append(i)
        gap = 0
        if trailing_unit:  # "40,000 rupees | 10,000 rupees": a unit word ends the amount
            close()
    close()
    for sp in spans:
        sp.has_currency = any(t.kind == "CURRENCY" for t in sp.tokens)
        sp.has_mult = any(t.kind == "MULT" for t in sp.tokens)
        sp.method = _method(sp.tokens)
    return spans


# ------------------------------------------------------------------ amount grammar
@dataclass
class _AmtCand:
    value: int | None
    strong: bool
    has_currency: bool
    tokens: list[Tok]
    warnings: list[str]


class _AmtState:
    def __init__(self) -> None:
        self.total = 0.0
        self.group = 0.0
        self.slots: set[str] = set()
        self.last_mult: int | None = None
        self.started = False
        self.has_mult = False
        self.has_num = False
        self.has_words10 = False
        self.has_currency = False
        self.article = False
        self.tokens: list[Tok] = []
        self.range_flag = False

    def finish(self) -> _AmtCand | None:
        if not self.started:
            return None
        warnings: list[str] = []
        if "F" in self.slots:
            return _AmtCand(None, False, self.has_currency, self.tokens, ["dangling_fraction"])
        v = self.total + self.group
        if v != int(v):
            if self.has_currency and self.has_num:
                warnings.append("paise_dropped")
            else:
                return _AmtCand(None, False, self.has_currency, self.tokens, ["non_integer"])
        val = int(v)
        num_digits = sum(len(t.text) for t in self.tokens if t.kind == "NUM")
        strong = self.has_mult or self.has_currency or self.has_words10 or (self.has_num and num_digits < 10)
        if self.range_flag:
            warnings.append("range")
        if any(t.ambiguous for t in self.tokens):
            warnings.append("ambiguous")
        return _AmtCand(val, strong, self.has_currency, self.tokens, warnings)


def _amount_cands(toks: list[Tok]) -> list[_AmtCand]:
    cands: list[_AmtCand] = []
    st = _AmtState()
    pending_currency = False

    def restart(range_flag: bool = False) -> None:
        nonlocal st
        c = st.finish()
        if c:
            cands.append(c)
        st = _AmtState()
        st.range_flag = range_flag

    i = 0
    while i < len(toks):
        t = toks[i]
        k = t.kind
        if k in ("FILLER", "AND"):
            i += 1
            continue
        if k == "CURRENCY":
            if st.started:
                st.has_currency = True
                st.tokens.append(t)
            else:
                pending_currency = True
            i += 1
            continue
        if k == "ARTICLE":
            st.article = True
            i += 1
            continue
        if k in ("DOUBLE", "TRIPLE"):
            restart()
            i += 1
            continue
        if k == "WORD":
            restart()
            i += 1
            continue

        broke = False
        if k == "NUM" and st.group and not st.slots & {"H"} and t.value in (1000, 100000, 10000000)                 and (st.last_mult is None or t.value < st.last_mult):
            # ITN half-conversion: "ஒன்றரை 1,00,000" (ஒன்றரை லட்சம்) — the digit run is the multiplier
            k = "MULT"
        if k == "NUM":
            if st.started and (st.slots or st.last_mult is None or t.value >= st.last_mult):
                broke = True
            else:
                st.group = float(t.value)
                st.slots = {"H", "T", "U"}
                st.has_num = True
        elif k == "UNIT":
            if "U" in st.slots or "F" in st.slots:
                single_unit = st.slots == {"U"} and st.last_mult is None
                restart(range_flag=single_unit)
                continue
            st.group += t.value
            st.slots.add("U")
        elif k == "TEEN":
            if st.slots & {"T", "U", "F"}:
                broke = True
            else:
                st.group += t.value
                st.slots |= {"T", "U"}
                st.has_words10 = True
        elif k == "TENS":
            if st.slots & {"T", "U", "F"}:
                broke = True
            else:
                st.group += t.value
                st.slots.add("T")
                st.has_words10 = True
        elif k == "HUND":
            if st.slots:
                broke = True
            else:
                st.group += t.value
                st.slots.add("H")
                st.has_words10 = True
        elif k == "HUNDRED":
            if "H" in st.slots or "F" in st.slots or st.group >= 100:
                broke = True
            else:
                st.group = (st.group or 1) * 100
                st.slots = {"H"}
                st.has_words10 = True
        elif k == "FRAC":
            if "F" in st.slots:
                broke = True
            else:
                st.group += t.value
                st.slots.add("F")
        elif k == "MULT":
            m = int(t.value)
            if st.last_mult is not None and m >= st.last_mult:
                broke = True  # multipliers must decrease: "ஆயிரம் ... ஆயிரம்" starts a new number
            else:
                g = st.group if st.group else 1
                st.total += g * m
                st.group = 0
                st.slots = set()
                st.last_mult = m
                st.has_mult = True
        if broke:
            restart()
            continue
        if not st.started and pending_currency:
            st.has_currency = True
        pending_currency = False
        st.started = True
        st.tokens.append(t)
        i += 1
    restart()
    return cands


# ------------------------------------------------------------------ digit strings
def _span_digits(toks: list[Tok], warnings: list[str]) -> str:
    vt = [t for t in toks if t.kind not in ("FILLER", "AND", "CURRENCY", "ARTICLE")]
    out: list[str] = []
    rep = 1
    i = 0
    while i < len(vt):
        t = vt[i]
        nxt = vt[i + 1] if i + 1 < len(vt) else None
        d = ""
        if t.kind == "DOUBLE":
            rep = 2
        elif t.kind == "TRIPLE":
            rep = 3
        elif t.kind == "UNIT":
            d = str(int(t.value))
        elif t.kind == "NUM":
            d = re.sub(r"\D", "", t.text)
        elif t.kind == "TEEN":
            d = str(int(t.value))
        elif t.kind == "TENS":
            # "ninety eight" / fused "தொண்ணூற்றெட்டு" -> "98"
            if nxt is not None and nxt.kind == "UNIT" and nxt.value != 0 and (nxt.word == t.word or t.tag == "en"):
                d = str(int(t.value + nxt.value))
                i += 1
            else:
                d = str(int(t.value))
        elif t.kind == "HUND":
            total = t.value
            j = i + 1
            while j < len(vt) and vt[j].kind in ("TENS", "UNIT", "TEEN") and vt[j].word == t.word:
                total += vt[j].value
                j += 1
            i = j - 1
            d = str(int(total))
        else:
            warnings.append("non_digit_word")
        if d:
            if rep > 1:
                d = d[0] * rep + d[1:]
                rep = 1
            out.append(d)
        i += 1
    return "".join(out)


# ------------------------------------------------------------------ public API
def find_number_spans(transcript: str) -> list[Span]:
    ws, toks = tokenize(transcript)
    spans = _group_spans(ws, toks)
    for sp in spans:
        cands = [c for c in _amount_cands(sp.tokens) if c.value is not None and c.strong]
        if len(cands) == 1 and not cands[0].warnings:
            sp.amount, sp.amount_strong = cands[0].value, True
        sp.digits = _span_digits(sp.tokens, [])
    return spans


def parse_amount(s: str) -> ParseResult:
    ws, toks = tokenize(s)
    spans = _group_spans(ws, toks)
    warnings: list[str] = []
    strong: list[tuple[Span, _AmtCand]] = []
    for sp in spans:
        if not (sp.has_mult or sp.has_currency) and len(_span_digits(sp.tokens, [])) >= 10:
            continue  # looks like a phone / UTR read-out, not an amount
        for c in _amount_cands(sp.tokens):
            if c.value is None:
                warnings.extend(c.warnings)
            elif c.strong:
                strong.append((sp, c))
    if not strong:
        return ParseResult(None, spans, "none", sorted(set(warnings)))
    distinct = {c.value for _, c in strong}
    chosen: tuple[Span, _AmtCand] | None = None
    if len(distinct) == 1:
        chosen = strong[0]
    else:
        with_cur = [x for x in strong if x[1].has_currency]
        if len({c.value for _, c in with_cur}) == 1:
            chosen = with_cur[0]
    if chosen is None:
        return ParseResult(None, spans, "none", sorted(set(warnings + ["multiple_amounts"])))
    sp, c = chosen
    if "range" in c.warnings or "ambiguous" in c.warnings:
        return ParseResult(None, [sp], _method(c.tokens), sorted(set(warnings + c.warnings)))
    if c.value is not None and c.value <= 0:
        return ParseResult(None, [sp], _method(c.tokens), ["zero_amount"])
    return ParseResult(c.value, [sp], _method(c.tokens), sorted(set(c.warnings)))


def parse_digit_string(s: str, expected_len: int | None = None) -> ParseResult:
    ws, toks = tokenize(s)
    spans = _group_spans(ws, toks)
    warnings: list[str] = []
    singles: list[tuple[Span, str]] = []
    for sp in spans:
        d = _span_digits(sp.tokens, warnings)
        sp.digits = d
        if d:
            singles.append((sp, d))
    if not singles:
        return ParseResult(None, spans, "none", sorted(set(warnings)))
    if any(t.ambiguous for sp, _ in singles for t in sp.tokens):
        warnings.append("ambiguous")
    if expected_len:
        exact = [x for x in singles if len(x[1]) == expected_len]
        if len(exact) == 1:
            sp, d = exact[0]
            return ParseResult(d, [sp], sp.method, sorted(set(warnings)))
        if len(exact) > 1:
            return ParseResult(None, [x[0] for x in exact], "none", sorted(set(warnings + ["multiple_spans"])))
        concat = "".join(d for _, d in singles)
        if len(singles) > 1 and len(concat) == expected_len:
            all_toks = [t for sp, _ in singles for t in sp.tokens]
            return ParseResult(concat, [x[0] for x in singles], _method(all_toks),
                               sorted(set(warnings + ["merged_spans"])))
        sp, d = max(singles, key=lambda x: len(x[1]))
        return ParseResult(d, [sp], sp.method, sorted(set(warnings + ["length_mismatch"])))
    sp, d = max(singles, key=lambda x: len(x[1]))
    if len(singles) > 1:
        warnings.append("multiple_spans")
    return ParseResult(d, [sp], sp.method, sorted(set(warnings)))


def format_inr(n: int) -> str:
    """50000 -> '₹50,000'; 1234567 -> '₹12,34,567' (Indian grouping)."""
    s = str(n)
    if len(s) <= 3:
        return f"₹{s}"
    head, tail = s[:-3], s[-3:]
    parts: list[str] = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return "₹" + ",".join(parts + [tail])
