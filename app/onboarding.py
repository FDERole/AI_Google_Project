"""Teach Sanjaya a plant: draft the risk model from its own HAZOP and SOP documents.

Gemini reads the PDFs and proposes hazards, safeguards and limits, each with the page it
came from. Nothing is used until the safety officer reviews and approves the draft.
"""
import json
from typing import List, Optional

from pydantic import BaseModel

from .config import DATA_DIR
from .fallback import pdf_text

try:
    from google.genai import types
except ImportError:  # pragma: no cover
    types = None


class Source(BaseModel):
    doc: str
    section: str
    page: Optional[int] = None


class DraftBarrier(BaseModel):
    name: str
    tag: str
    source: Source


class DraftHazard(BaseModel):
    name: str
    area: str
    consequence: str
    source: Source
    barriers: List[DraftBarrier]


class DraftLimit(BaseModel):
    equipment: str
    action: str
    value: float
    unit: str
    condition: Optional[str] = None
    consequence: str
    source: Source


class RiskModelDraft(BaseModel):
    hazards: List[DraftHazard]
    limits: List[DraftLimit]
    gaps: List[str]


SAMPLE_DOCS = ["HZ-2024", "SOP-R201-07", "PV-SD1-2024", "AC-SR1", "SOP-SD1-03", "SOP-HR-05"]


def sample_attachments():
    return [{"kind": "document", "path": DATA_DIR / "docs" / f"{d}.pdf", "mime": "application/pdf",
             "name": f"{d}.pdf", "url": f"/media/docs/{d}.pdf"} for d in SAMPLE_DOCS]


def extract_with_gemini(gemini, attachments, known_tags):
    client = gemini.client
    parts = [types.Part.from_bytes(data=a["path"].read_bytes(), mime_type="application/pdf") for a in attachments]
    parts.append(f"""These are a chemical plant's safety documents (HAZOP report, SOPs, standards).
Draft the plant's risk model:
- hazards: each High-risk HAZOP scenario, with its consequence and the independent safeguards credited
  against it. For each safeguard choose a tag from {sorted(known_tags)} if one fits, otherwise invent a short
  snake_case tag ending with the equipment id (e.g. alarm_TAH-999).
- limits: every numeric operating limit stated in an SOP or validation report (value + unit), with the
  equipment id, the action it limits, any condition, and the consequence of exceeding it.
- gaps: things a safety officer should check because the documents are vague or silent.
Every item must cite its source: document id (as printed in the document header/footer), section or node id,
and page number. Use only what the documents say. Never invent numbers.""")
    resp = gemini.generate(
        contents=parts,
        config=types.GenerateContentConfig(response_mime_type="application/json",
                                           response_schema=RiskModelDraft, temperature=0))
    return RiskModelDraft.model_validate(json.loads(resp.text)).model_dump()


def draft_from_current_model(plant, docs):
    """Offline mode: the pre-computed extraction of the sample documents (= the model Sanjaya runs on)."""
    hazards = []
    for hz in plant.hazards:
        ref = hz.get("doc", {})
        sec = docs.get(ref.get("doc"), ref.get("section")) if ref else None
        hazards.append({
            "name": hz["name"], "area": hz["area"],
            "consequence": (sec["text"].split("Consequence:")[-1].split(".")[0].strip() if sec else ""),
            "source": {**ref, "page": sec["page"] if sec else None},
            "barriers": [{"name": b["name"], "tag": b["tag"], "source": {**ref, "page": sec["page"] if sec else None}}
                         for b in hz["barriers"]],
        })
    limits = []
    for lim in plant.limits:
        ref = lim.get("doc", {})
        sec = docs.get(ref.get("doc"), ref.get("section")) if ref else None
        value = lim.get("max_minutes") or lim.get("max_value") or lim.get("min_value")
        limits.append({"equipment": lim["equipment"], "action": lim["action"], "value": value,
                       "unit": "min" if lim.get("max_minutes") else lim.get("unit", ""),
                       "condition": lim.get("condition"), "consequence": lim["consequence_en"],
                       "source": {**ref, "page": sec["page"] if sec else None}})
    gaps = ["SOP-R201-07 gives no limit for shutting down Boiler B-1 when no batch is in hold.",
            "No documented maximum time for Gas detector GD-07 to be out of service.",
            "The HAZOP doesn't rank simultaneous impairment of two or more safeguards (section 2)."]
    return {"hazards": hazards, "limits": limits, "gaps": gaps}


def pages_of(attachment):
    text = pdf_text(attachment["path"])
    return max(1, text.count("· page")) if text else 1
