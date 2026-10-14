"""Gemini calls. Every call returns structured JSON validated by a schema.

Gemini reads text, photos, voice notes and datasheets and classifies them.
It never decides limits: numbers it reports are checked against the plant's
documented data by the deterministic code in engine.py and parts.py.
"""
import json
import logging
import re
import time
from typing import List, Literal, Optional

from pydantic import BaseModel

from .config import GEMINI_API_KEY, GEMINI_MODEL

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover
    genai = None


log = logging.getLogger("sanjaya.gemini")

# Last-resort names if listing models fails. Normally the model is picked from what the key can use.
FALLBACK_MODELS = ["gemini-3.8-flash", "gemini-flash-latest", "gemini-2.5-flash"]
SKIP = ("image", "tts", "embedding", "live", "audio", "aqa", "computer", "robotics", "learnlm", "nano", "gemma")


def _version(name):
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else 0.0


def _rank(name):
    """Prefer the newest stable Flash: fast enough for live chat, smart enough for tools and JSON."""
    if not name.startswith("gemini") or any(k in name for k in SKIP):
        return None
    score = _version(name) * 10 if "latest" not in name else 1
    if "flash" in name and "lite" not in name:
        score += 3
    elif "flash-lite" in name:
        score += 1
    if "preview" in name or "exp" in name:
        score -= 2
    return score


def _gone(exc):
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return code == 404 or "NOT_FOUND" in str(exc) or "no longer available" in str(exc)


def _transient(exc):
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    text = str(exc)
    return code in (429, 500, 503, 504) or any(k in text for k in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "overloaded", "high demand"))


class Interpretation(BaseModel):
    transcript: Optional[str] = None
    kind: Literal["chat", "routine_change", "change_request", "part_evaluation", "unreviewed_part_change",
                  "started", "finished"]
    summary: str
    tags: List[str]
    equipment: Optional[str] = None
    action: Optional[str] = None
    requested_minutes: Optional[int] = None
    model: Optional[str] = None
    seen: Optional[str] = None


class Decision(BaseModel):
    transcript: Optional[str] = None
    decision: Literal["approve", "approve_with_conditions", "reject", "unclear"]
    max_minutes: Optional[int] = None
    conditions: Optional[str] = None


class Confirmation(BaseModel):
    transcript: Optional[str] = None
    answer: Literal["yes", "no", "unclear"]


class Specs(BaseModel):
    model: Optional[str] = None
    airflow_m3h: Optional[int] = None
    ex_marking: Optional[str] = None
    temperature_class: Optional[str] = None
    impeller_material: Optional[str] = None
    price_inr: Optional[int] = None


class Gemini:
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY) if (genai and GEMINI_API_KEY) else None

    model = GEMINI_MODEL or FALLBACK_MODELS[0]
    candidates = list(FALLBACK_MODELS)
    live_model = None
    status = "unchecked"   # unchecked | ok | failed
    error = None

    @property
    def available(self):
        return self.client is not None and self.status != "failed"

    def generate(self, **kwargs):
        """generate_content that keeps working when a model is busy or retired.

        503/429 (overloaded, rate limited): retry once, then move to the next working model.
        404 (model retired for this key): move to the next model straight away.
        Anything else (bad key, bad request) is raised at once.
        """
        models = list(dict.fromkeys([self.model] + self.candidates))
        last = None
        for i, name in enumerate(models):
            for attempt in range(2 if i == 0 else 1):
                try:
                    resp = self.client.models.generate_content(model=name, **kwargs)
                    if name != self.model:
                        log.warning("Gemini %s unavailable; switched to %s", self.model, name)
                        self.model = name
                    return resp
                except Exception as exc:
                    last = exc
                    if _gone(exc):
                        break
                    if not _transient(exc):
                        raise
                    log.warning("Gemini %s busy (%s)", name, str(exc)[:80])
                    if attempt == 0 and i == 0:
                        time.sleep(0.8)
        raise last

    def discover(self):
        """Ask Google which models this key can use. Model names get retired, so never rely on one."""
        text, live = [], []
        try:
            for m in self.client.models.list():
                name = (m.name or "").split("/")[-1]
                actions = m.supported_actions or []
                if "generateContent" in actions and _rank(name) is not None:
                    text.append(name)
                if "bidiGenerateContent" in actions and ("live" in name or "native-audio" in name):
                    live.append(name)
        except Exception as exc:
            log.warning("Couldn't list Gemini models: %s", str(exc)[:160])
        text.sort(key=_rank, reverse=True)
        live.sort(key=lambda n: (_version(n), "preview" not in n), reverse=True)
        return text, live

    def check(self):
        """Find a model that actually answers with this key. Called once at startup (and by /api/gemini)."""
        if self.client is None:
            return
        discovered, live = self.discover()
        if live:
            self.live_model = live[0]
        explicit = [GEMINI_MODEL] if GEMINI_MODEL else []
        queue = list(dict.fromkeys(explicit + discovered[:6] + FALLBACK_MODELS))
        errors, tried = [], set()
        while queue:
            name = queue.pop(0)
            if name in tried:
                continue
            tried.add(name)
            try:
                resp = self.client.models.generate_content(model=name, contents="Reply with the word OK.")
                if resp.text:
                    self._ready(name, [n for n in discovered + FALLBACK_MODELS if n != name])
                    return
            except Exception as exc:
                errors.append(f"{name}: {str(exc)[:160]}")
                suggested = re.search(r"use models/([\w.\-]+)", str(exc))
                if suggested:
                    queue.insert(0, suggested.group(1))  # the API told us which model to use
                elif _transient(exc):
                    # Busy right now, but this key can use it: go with it; calls retry and fall back.
                    self._ready(name, [n for n in discovered + FALLBACK_MODELS if n != name])
                    return
        self.status = "failed"
        self.error = " | ".join(errors)[:600]
        log.error("No Gemini model worked, running offline. %s", self.error)

    def _ready(self, name, others):
        self.model, self.status, self.error = name, "ok", None
        self.candidates = list(dict.fromkeys(others))[:5]
        log.info("Gemini ready: model %s (fallbacks %s), live model %s", name, self.candidates, self.live_model)

    def _call(self, prompt, schema, attachments=()):
        parts = []
        for att in attachments:
            parts.append(types.Part.from_bytes(data=att["bytes"], mime_type=att["mime"]))
        parts.append(prompt)
        resp = self.generate(
            contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0,
            ),
        )
        return schema.model_validate(json.loads(resp.text)).model_dump()

    def interpret(self, text, author, plant, attachments=(), context=""):
        tags = sorted({b["tag"] for h in plant.hazards for b in h["barriers"]})
        equipment = {e["id"]: e["name"] for e in plant.equipment.values()}
        prompt = f"""You are Sanjaya, the safety agent inside the group chat of an Indian chemical plant.
A member posted the message below (text, and possibly a photo, voice note or document attached).
Messages may be in English, Hindi or Hinglish.

Author: {author['name']} ({author['title']})
Message text: {text or '(none)'}
{context}

Classify it:
- "routine_change": something on the floor changed that may weaken a safeguard (batch size raised,
  alarm muted or bypassed, new or trainee worker on a shift, detector or fan in maintenance, hot work...).
- "change_request": the author asks permission to do something to equipment (e.g. shut down a boiler).
- "part_evaluation": someone asks to evaluate a replacement part or a new supplier.
- "unreviewed_part_change": a part was already replaced/installed (e.g. photo of a new nameplate, invoice).
- "started" / "finished": the author reports starting or finishing an approved change.
- "chat": anything else.

tags: choose ONLY from this list the safeguard tags the change weakens: {tags}
equipment: one id from {json.dumps(equipment)} or null.
action: "shutdown" for shutdown requests, otherwise null.
requested_minutes: only if the author states a duration.
model: maker and model of any part seen (e.g. on a nameplate), else null.
seen: one sentence describing what any photo shows, else null.
transcript: if a voice note is attached, its exact transcript in the original language, else null.
summary: one short English sentence for the plant's change log.
Never invent numbers that are not in the message."""
        return self._call(prompt, Interpretation, attachments)

    def parse_decision(self, text, request_summary, attachments=()):
        prompt = f"""An approver is replying (text or voice, English/Hindi/Hinglish) to this request: "{request_summary}".
Reply text: {text or '(voice note attached)'}
Return the decision. "approve_with_conditions" if they set a time limit or condition; put the limit in
max_minutes. "unclear" if you cannot tell. If a voice note is attached, include its transcript."""
        return self._call(prompt, Decision, attachments)

    def parse_confirmation(self, text, readback, attachments=()):
        prompt = f"""Sanjaya read back a decision: "{readback}". The approver replied: {text or '(voice note attached)'}
Is that a yes (confirming), a no (correcting), or unclear? Include the transcript of any voice note."""
        return self._call(prompt, Confirmation, attachments)

    def transcribe(self, attachments):
        prompt = ("Transcribe this voice note exactly, in its original language (Hindi in Devanagari, Hinglish "
                  "in Latin script, English as spoken). Return only the transcript, or an empty string if silent.")
        parts = [types.Part.from_bytes(data=a["bytes"], mime_type=a["mime"]) for a in attachments] + [prompt]
        resp = self.generate(contents=parts)
        return (resp.text or "").strip()

    def extract_specs(self, attachment):
        prompt = """This is a datasheet (or nameplate photo) for an industrial exhaust fan.
Extract ONLY values that are explicitly stated. If a value is not stated, return null - never guess.
model: maker + model name. airflow_m3h: rated airflow in m3/h. ex_marking: the full hazardous-area
marking (e.g. "Ex db IIB T4 Gb") or null. temperature_class: e.g. "T4". impeller_material: as written.
price_inr: price in rupees as an integer."""
        return self._call(prompt, Specs, [attachment])


AGENT_TOOLS = [
    ("get_risk_stacks", "Live risk stack: every hazard, its level and which safeguards are weakened right now.", {}),
    ("get_active_changes", "Changes currently active on the plant floor.", {}),
    ("get_requests", "Approval requests and their status.", {}),
    ("search_documents", "Search the plant's HAZOP, SOPs and standards. Returns sections with citations.",
     {"query": "What to search for, in English"}),
    ("get_limit", "Documented limit for an action on a piece of equipment.",
     {"equipment_id": "Equipment id such as B-1", "action": "Action such as shutdown"}),
]


def _numbers(text):
    return set(re.findall(r"\d+(?:[.,]\d+)*", text or ""))


def _ask(self, question, asker, tool_call, on_tool):
    declarations = []
    for name, desc, params in AGENT_TOOLS:
        schema = types.Schema(type="OBJECT", properties={k: types.Schema(type="STRING", description=v)
                                                         for k, v in params.items()},
                              required=list(params)) if params else None
        declarations.append(types.FunctionDeclaration(name=name, description=desc, parameters=schema))
    lang = {"hi-IN": "Hindi (Hinglish is fine)", "te-IN": "Telugu"}.get(asker.get("lang"), "English")
    system = (
        "You are Sanjaya, the safety agent of an Indian chemical plant (Plant X). Answer the worker's question "
        f"in {lang}, in at most 3 short spoken sentences. Use the tools to look things up. Every number, limit "
        "or rule you state must come from a tool result, and name its citation (e.g. 'SOP-R201-07 §4.2'). If the "
        "tools don't have it, say you don't know. You never approve changes and never operate equipment."
    )
    contents = [types.Content(role="user", parts=[types.Part(text=f"{asker['name']} ({asker['title']}) asks: {question}")])]
    seen_numbers = _numbers(question)
    config = types.GenerateContentConfig(
        system_instruction=system, temperature=0.2,
        tools=[types.Tool(function_declarations=declarations)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    for _ in range(6):
        resp = self.generate(contents=contents, config=config)
        calls = resp.function_calls or []
        if not calls:
            answer = (resp.text or "").strip()
            # Guardrail: refuse answers that contain numbers no tool returned.
            if not answer or not _numbers(answer) <= seen_numbers:
                return None
            return answer
        contents.append(resp.candidates[0].content)
        responses = []
        for call in calls:
            args = dict(call.args or {})
            result = tool_call(call.name, args)
            on_tool(call.name, args, result)
            seen_numbers |= _numbers(json.dumps(result, ensure_ascii=False))
            responses.append(types.Part.from_function_response(name=call.name, response={"result": result}))
        contents.append(types.Content(role="user", parts=responses))
    return None


Gemini.ask = _ask
