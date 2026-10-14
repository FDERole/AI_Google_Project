"""Scripted fallback mode: keyword rules that understand the demo's English, Hinglish and Hindi.

Used when no Gemini key is set or a Gemini call fails, so the demo never dies on stage.
Returns exactly the same shapes as the Gemini path (see brain.py).
"""
import re

from pypdf import PdfReader

WORD_NUMBERS = {
    "five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "twenty five": 25, "thirty": 30,
    "paanch": 5, "panch": 5, "das": 10, "pandrah": 15, "pandra": 15, "bees": 20, "pachchis": 25, "tees": 30,
    "पांच": 5, "पाँच": 5, "दस": 10, "पंद्रह": 15, "बीस": 20, "पच्चीस": 25, "तीस": 30,
}

# (tag, subject pattern, change pattern, summary, equipment)
ROUTINE_RULES = [
    ("batch_size", r"batch|बैच", r"increas|badh|बढ़|scale|zyada|ज़्यादा|ज्यादा|\d+\s*(kg|kilo|किलो)",
     "Batch size increased above the validated limit", "SD-1"),
    ("alarm_TAH-301", r"alarm|अलार्म|tah", r"mute|bypass|silenc|disabl|band|बंद|off",
     "Dryer high-temp alarm TAH-301 muted / bypassed", "TAH-301"),
    ("crew_training", r"trainee|new worker|new operator|naya|नया|नए|first day|pehla din",
     r"shift|night|raat|रात|add|join",
     "Untrained / new worker added to the shift", None),
    ("gas_detector_GD-07", r"gas detector|detector|gd-?07", r"maintenance|repair|calibrat|remov|off|band|बंद|service",
     "Gas detector GD-07 under maintenance", "GD-07"),
    ("nitrogen_SD-1", r"nitrogen|\bn2\b", r"low|off|band|बंद|stop|kam|कम",
     "Nitrogen inerting on SD-1 reduced / off", "SD-1"),
    ("hot_work", r"weld|hot work|grind|cutting|gas cutting", r".",
     "Hot work started", None),
    ("alarm_TAH-201", r"tah-?201|reactor alarm", r"mute|bypass|band|बंद|off",
     "Reactor high-temp alarm TAH-201 bypassed", "TAH-201"),
]

REQUEST_ACTIONS = [
    ("shutdown", r"shut ?down|shut|band kar|बंद कर|switch off|turn off|\boff\b|बंद"),
]
REQUEST_PHRASING = r"can i|may i|shall i|should i|please|need to|want to|karna hai|karna h|karu|karun|kar du|kar doon|kya|\?|request|allow|permission|chahiye|चाहिए|करना है|^shut|^switch|^turn"

STARTED = r"\bstart(ed|ing)?\b|shuru|शुरू|band kar diya|बंद कर दिया|switched off|turned off|is off now|off now|abhi band"
FINISHED = r"back on|restart|chalu kar|चालू|on kar diya|wapas|वापस|\bdone\b|complete|finished|khatam|ख़त्म|खत्म"

PART_EVAL = r"evaluat|risk|compare|check|review|go through|dekh"
PART_SUBJECT = r"supplier|vendor|datasheet|fan|पंखा|part"
PART_REPLACED = r"replac|changed|badal|बदल|installed|lagaya|लगाया|new fan|naya fan|नया पंखा"


def _has(pattern, text):
    return re.search(pattern, text, re.IGNORECASE) is not None


def find_minutes(text):
    m = re.search(r"(?<![\w-])(\d{1,3})\s*(min|minute|mins|मिनट|minat|m\b)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # A bare number counts too ("yes, 15 max"), but not equipment tags like B-1 or R-201.
    m = re.search(r"(?<![\w-])(\d{1,3})(?![\w-])", text)
    if m and 1 <= int(m.group(1)) <= 180:
        return int(m.group(1))
    low = text.lower()
    for word in sorted(WORD_NUMBERS, key=len, reverse=True):
        if re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", low):
            return WORD_NUMBERS[word]
    return None


def interpret(text, plant, attachments=()):
    """Classify a group-chat post. Attachments are dicts with keys kind, name, demo_meta."""
    text = text or ""
    for att in attachments:
        meta = att.get("demo_meta")
        if meta:
            return {
                "kind": meta["kind"], "summary": meta["summary"], "tags": meta["tags"],
                "equipment": meta.get("equipment"), "action": None, "requested_minutes": None,
                "model": meta.get("model"), "seen": meta["description"],
            }

    has_docs = any(a.get("kind") == "document" for a in attachments)
    equipment = plant.find_equipment(text)

    if (has_docs and _has(PART_EVAL + "|" + PART_SUBJECT, text)) or (
        _has(PART_EVAL, text) and _has(r"supplier|vendor|datasheet", text)
    ):
        return _result("part_evaluation", "Evaluate a replacement part from a new supplier",
                       [], equipment or "EF-04")

    if _has(PART_SUBJECT, text) and _has(PART_REPLACED, text) and not _has(r"planning|plan to|want to|should we", text):
        return _result("unreviewed_part_change", "Part replaced without review", ["fan_EF-04"], equipment or "EF-04")

    if equipment:
        for action, pattern in REQUEST_ACTIONS:
            if _has(pattern, text) and _has(REQUEST_PHRASING, text.strip()) and not _has(STARTED, text):
                eq = plant.equipment[equipment]["name"]
                return _result("change_request", f"Shut down {eq}", [], equipment, action=action,
                               requested_minutes=find_minutes(text))

    tags, summaries, eq_hit = [], [], equipment
    for tag, subject, change, summary, eq in ROUTINE_RULES:
        if _has(subject, text) and _has(change, text):
            tags.append(tag)
            summaries.append(summary)
            eq_hit = eq_hit or eq
    if tags:
        return _result("routine_change", "; ".join(summaries), tags, eq_hit)

    return _result("chat", "", [], equipment)


def _result(kind, summary, tags, equipment, action=None, requested_minutes=None):
    return {"kind": kind, "summary": summary, "tags": tags, "equipment": equipment,
            "action": action, "requested_minutes": requested_minutes, "model": None, "seen": None}


def is_started(text):
    return _has(STARTED, text or "")


def is_finished(text):
    return _has(FINISHED, text or "")


def parse_decision(text):
    t = (text or "").lower()
    minutes = find_minutes(t)
    cleaned = re.sub(r"no more than|not more than|nahi zyada|se zyada nahi|से ज़्यादा नहीं|se jyada nahi", " max ", t)
    if _has(r"\bno\b|nahi|nahin|नहीं|reject|don'?t|do not|\bmat\b|deny|not allowed|ruk|wait", cleaned):
        return {"decision": "reject", "max_minutes": None, "conditions": None}
    if _has(r"\byes\b|haan|\bha\b|हाँ|हां|\bok\b|okay|approve|allow|kar do|kar sakte|theek|ठीक|go ahead|fine|sure|max", cleaned):
        if minutes:
            return {"decision": "approve_with_conditions", "max_minutes": minutes,
                    "conditions": f"maximum {minutes} minutes"}
        return {"decision": "approve", "max_minutes": None, "conditions": None}
    return {"decision": "unclear", "max_minutes": None, "conditions": None}


def parse_confirmation(text):
    t = (text or "").lower()
    if _has(r"\bno\b|nahi|नहीं|wrong|galat|गलत|change|incorrect", t):
        return "no"
    if _has(r"\byes\b|haan|\bha\b|हाँ|हां|correct|sahi|सही|right|confirm|\bok\b|okay|theek", t):
        return "yes"
    return "unclear"


# ---- Datasheet reading ----------------------------------------------------

def pdf_text(path):
    try:
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    except Exception:
        return ""


def extract_specs(text):
    """Pull the safety-relevant specs out of datasheet text. Missing values stay None."""
    specs = {"model": None, "airflow_m3h": None, "ex_marking": None, "temperature_class": None,
             "impeller_material": None, "price_inr": None}
    maker = re.search(r"^(.*(?:Systems|Fans|Pvt Ltd|Ltd|Inc).*)$", text, re.MULTILINE)
    model = re.search(r"Model\s*[:\-]?\s*([A-Z]{1,4}-?\d{2,4}[A-Z]?)", text)
    if model:
        brand = maker.group(1).split()[0] if maker else ""
        specs["model"] = f"{brand} {model.group(1)}".strip()
    air = re.search(r"([\d,]{4,7})\s*m(?:3|³)\s*/\s*h", text)
    if air:
        specs["airflow_m3h"] = int(air.group(1).replace(",", ""))
    ex = re.search(r"(Ex\s+[a-z]{1,3}\s+II[ABC]?\s*T\d\s*G[abc])", text)
    if ex:
        specs["ex_marking"] = re.sub(r"\s+", " ", ex.group(1))
    tc = re.search(r"Temperature class\s*[:\-]?\s*(T\d)", text, re.IGNORECASE) or re.search(r"\b(T[1-6])\b", text)
    if tc:
        specs["temperature_class"] = tc.group(1).upper()
    imp = re.search(r"Impeller material\s*[:\-]?\s*(.+)", text, re.IGNORECASE)
    if imp:
        specs["impeller_material"] = imp.group(1).strip()
    price = re.search(r"(?:INR|Rs\.?|₹)\s*([\d,]+)", text)
    if price:
        specs["price_inr"] = int(price.group(1).replace(",", ""))
    return specs
