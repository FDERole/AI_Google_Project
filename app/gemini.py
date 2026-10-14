"""Gemini calls. Every call returns structured JSON validated by a schema.

Gemini reads text, photos, voice notes and datasheets and classifies them.
It never decides limits: numbers it reports are checked against the plant's
documented data by the deterministic code in engine.py and parts.py.
"""
import json
from typing import List, Literal, Optional

from pydantic import BaseModel

from .config import GEMINI_API_KEY, GEMINI_MODEL

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover
    genai = None


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

    @property
    def available(self):
        return self.client is not None

    def _call(self, prompt, schema, attachments=()):
        parts = []
        for att in attachments:
            parts.append(types.Part.from_bytes(data=att["bytes"], mime_type=att["mime"]))
        parts.append(prompt)
        resp = self.client.models.generate_content(
            model=GEMINI_MODEL,
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
        prompt = "Transcribe this voice note exactly, in its original language. Return only the transcript."
        parts = [types.Part.from_bytes(data=a["bytes"], mime_type=a["mime"]) for a in attachments] + [prompt]
        resp = self.client.models.generate_content(model=GEMINI_MODEL, contents=parts)
        return resp.text.strip()

    def extract_specs(self, attachment):
        prompt = """This is a datasheet (or nameplate photo) for an industrial exhaust fan.
Extract ONLY values that are explicitly stated. If a value is not stated, return null - never guess.
model: maker + model name. airflow_m3h: rated airflow in m3/h. ex_marking: the full hazardous-area
marking (e.g. "Ex db IIB T4 Gb") or null. temperature_class: e.g. "T4". impeller_material: as written.
price_inr: price in rupees as an integer."""
        return self._call(prompt, Specs, [attachment])
