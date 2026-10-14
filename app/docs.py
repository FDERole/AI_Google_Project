"""The plant's document library: HAZOP, SOPs and standards, searchable by section with page citations."""
import json
import math
import re
from collections import Counter

from .config import DATA_DIR

STOP = set("the a an of to and or in on for is be by with at as it this that from are must may any all its not".split())


def _tokens(text):
    return [t for t in re.findall(r"[a-z0-9][a-z0-9\-]*", text.lower()) if t not in STOP]


class Library:
    def __init__(self, path=DATA_DIR / "docs" / "index.json"):
        self.sections = json.loads(path.read_text(encoding="utf-8"))
        self._tf = [Counter(_tokens(s["heading"] + " " + s["text"])) for s in self.sections]
        df = Counter(t for tf in self._tf for t in tf)
        n = len(self.sections)
        self._idf = {t: math.log(1 + n / c) for t, c in df.items()}

    def get(self, doc, section):
        return next((s for s in self.sections if s["doc"] == doc and s["section"] == section), None)

    def cite(self, ref):
        """{'doc','section'} -> 'SOP-R201-07 §4.2, p.1'"""
        if not ref:
            return None
        s = self.get(ref["doc"], ref["section"])
        sec = ref["section"]
        if sec.startswith("T") and sec[1:].isdigit():
            label = f"Table {sec[1:]}"
        elif ref["doc"].startswith("HZ") and not sec.isdigit():
            label = f"Node {sec}"
        else:
            label = f"§{sec}"
        return f"{ref['doc']} {label}" + (f", p.{s['page']}" if s else "")

    def search(self, query, k=3):
        q = _tokens(query)
        scored = []
        for s, tf in zip(self.sections, self._tf):
            score = sum(tf[t] * self._idf.get(t, 0) for t in q)
            if score:
                scored.append((score, s))
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:k]]

    def snippet(self, ref, max_len=220):
        s = self.get(ref["doc"], ref["section"])
        if not s:
            return ""
        text = s["text"]
        return text if len(text) <= max_len else text[:max_len].rsplit(" ", 1)[0] + "…"
