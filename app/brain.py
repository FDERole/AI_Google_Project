"""Sanjaya's understanding layer: Gemini first, scripted fallback if Gemini is off or fails."""
import logging

from . import fallback
from .gemini import Gemini

log = logging.getLogger("sanjaya.brain")


def _gemini_parts(attachments):
    parts = []
    for att in attachments:
        if att.get("path") and att.get("mime"):
            parts.append({"bytes": att["path"].read_bytes(), "mime": att["mime"]})
    return parts


class Brain:
    def __init__(self, plant):
        self.plant = plant
        self.gemini = Gemini()
        self.force_offline = False

    @property
    def mode(self):
        return "gemini" if (self.gemini.available and not self.force_offline) else "offline"

    def _try(self, fn, *args):
        if self.mode != "gemini":
            return None
        try:
            return fn(*args)
        except Exception as exc:  # network, quota, schema - fall back, never crash the demo
            log.warning("Gemini call failed, using fallback: %s", exc)
            return None

    def interpret(self, text, author_id, attachments=(), context=""):
        author = self.plant.user(author_id)
        result = self._try(self.gemini.interpret, text, author, self.plant, _gemini_parts(attachments), context)
        if result:
            result["tags"] = [t for t in result["tags"] if t in self._known_tags()]
            if result.get("equipment") not in self.plant.equipment:
                result["equipment"] = None
            return result, "gemini"
        return fallback.interpret(text, self.plant, attachments), "offline"

    def transcribe(self, attachments, client_transcript=None):
        voice = [a for a in attachments if a.get("kind") == "voice"]
        if voice:
            result = self._try(self.gemini.transcribe, _gemini_parts(voice))
            if result:
                return result, "gemini"
        return client_transcript, "offline"

    def parse_decision(self, text, request_summary, attachments=()):
        result = self._try(self.gemini.parse_decision, text, request_summary, _gemini_parts(attachments))
        if result:
            return result, "gemini"
        return fallback.parse_decision(text), "offline"

    def parse_confirmation(self, text, readback, attachments=()):
        result = self._try(self.gemini.parse_confirmation, text, readback, _gemini_parts(attachments))
        if result:
            return result["answer"], "gemini"
        return fallback.parse_confirmation(text), "offline"

    def ask(self, question, asker, tool_call, on_tool):
        """Free-form question -> Gemini function-calling agent over read-only plant tools. None if offline."""
        return self._try(self.gemini.ask, question, asker, tool_call, on_tool), "gemini"

    def extract_specs(self, attachment):
        if attachment.get("demo_specs"):
            return attachment["demo_specs"], "offline"
        result = self._try(self.gemini.extract_specs, (_gemini_parts([attachment]) or [None])[0])
        if result:
            return result, "gemini"
        if attachment.get("mime") == "application/pdf":
            return fallback.extract_specs(fallback.pdf_text(attachment["path"])), "offline"
        return fallback.extract_specs(attachment.get("text", "")), "offline"

    def _known_tags(self):
        return {b["tag"] for h in self.plant.hazards for b in h["barriers"]}
