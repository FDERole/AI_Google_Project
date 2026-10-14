"""The plant's documented data: people, equipment, hazards, safeguards and limits."""
import json
import re

from .config import DATA_DIR


class Plant:
    def __init__(self, path=DATA_DIR / "plant_x.json"):
        self.data = json.loads(path.read_text(encoding="utf-8"))
        self.info = self.data["plant"]
        self.users = {u["id"]: u for u in self.data["users"]}
        self.equipment = {e["id"]: e for e in self.data["equipment"]}
        self.hazards = self.data["hazards"]
        self.limits = self.data["limits"]
        self.part_requirements = self.data["part_requirements"]

    def user(self, user_id):
        return self.users.get(user_id)

    def name(self, user_id):
        if user_id == "sanjaya":
            return "Sanjaya"
        u = self.users.get(user_id)
        return u["name"] if u else user_id

    def approvers(self, level):
        return [u["id"] for u in self.users.values() if u.get("approver_level") == level]

    def max_approver_level(self):
        return max((u.get("approver_level", 0) for u in self.users.values()), default=0)

    def risk_watchers(self):
        """People who hear risk-stack alerts: level-1 approvers and the safety officer."""
        ids = set(self.approvers(1))
        ids.update(u["id"] for u in self.users.values() if u.get("risk_alerts"))
        return sorted(ids)

    def find_equipment(self, text):
        """Return the equipment id mentioned in free text (English, Hinglish or Hindi), if any."""
        t = text.lower()
        best = None
        for eq in self.equipment.values():
            for alias in [eq["id"].lower()] + eq["aliases"]:
                if re.search(r"(?<![\w-])" + re.escape(alias.lower()) + r"(?![\w-])", t) or (
                    not alias.isascii() and alias in text
                ):
                    # Prefer the longest alias match ("gas detector" over "detector").
                    if best is None or len(alias) > best[1]:
                        best = (eq["id"], len(alias))
        return best[0] if best else None

    def find_limit(self, equipment_id, action):
        for lim in self.limits:
            if lim["equipment"] == equipment_id and lim["action"] == action:
                return lim
        return None

    def hazard(self, hazard_id):
        return next((h for h in self.hazards if h["id"] == hazard_id), None)

    def hazards_for_tags(self, tags):
        tags = set(tags)
        return [h for h in self.hazards if any(b["tag"] in tags for b in h["barriers"])]
