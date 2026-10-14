"""Like-for-like check for replacement parts.

Gemini (or the fallback) only *reads* the datasheets. The pass/fail judgement is
deterministic code against the plant's documented requirements, so a verdict
can always be traced to a cited rule.
"""
import re

SPARK_RESISTANT = r"spark[- ]?resistant|non[- ]?sparking|alumin|bronze|brass|frp|copper"
TEMP_ORDER = {"T1": 1, "T2": 2, "T3": 3, "T4": 4, "T5": 5, "T6": 6}


def inr(n):
    """Indian digit grouping: 180000 -> ₹1,80,000."""
    s = str(int(n))
    if len(s) <= 3:
        return "₹" + s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "₹" + ",".join(groups + [tail])


def _fmt(key, value):
    if value is None:
        return "Not stated"
    if key == "airflow_m3h":
        return f"{value:,} m³/h"
    if key == "price_inr":
        return inr(value)
    return str(value)


def check(req, value, current_value=None):
    """Return (status, note). status: pass | fail | missing | info."""
    rule = req["rule"]
    if rule == "info":
        if value is not None and current_value is not None:
            diff = current_value - value
            if diff > 0:
                return "info", f"Saves {inr(diff)}"
            if diff < 0:
                return "info", f"Costs {inr(-diff)} more"
        return "info", ""
    if value in (None, ""):
        return "missing", "Missing: must be provided"
    if rule == "min":
        if value >= req["value"]:
            return "pass", "Meets requirement"
        pct = (req["value"] - value) / req["value"] * 100
        return "fail", f"Fails: {pct:.1f}% below required minimum"
    if rule == "ex_gas_group":
        marking = str(value)
        if not re.search(r"\bEx\b", marking):
            return "missing", "Missing: no Ex marking"
        if any(g in marking for g in req["value"]):
            return "pass", "Certified for the zone"
        return "fail", "Fails: wrong gas group for this zone"
    if rule == "temp_class":
        got = TEMP_ORDER.get(str(value).upper()[:2])
        need = TEMP_ORDER[req["value"]]
        if got is None:
            return "missing", "Missing: unclear temperature class"
        if got >= need:
            return "pass", "Meets requirement"
        return "fail", "Fails: runs hotter than the zone allows"
    if rule == "spark_resistant":
        if re.search(SPARK_RESISTANT, str(value), re.IGNORECASE):
            return "pass", "Spark-resistant"
        return "fail", "Fails: spark risk in a solvent zone"
    return "missing", "Unknown rule"


def evaluate(plant, equipment_id, current, proposed, active_tags=()):
    spec = plant.part_requirements[equipment_id]
    rows, problems, conditions = [], [], []
    for req in spec["requirements"]:
        key = req["key"]
        status, note = check(req, proposed.get(key), current.get(key))
        rows.append({
            "label": req["label"], "key": key,
            "current": _fmt(key, current.get(key)), "proposed": _fmt(key, proposed.get(key)),
            "status": status, "note": note, "source": req.get("source"),
        })
        if status in ("fail", "missing"):
            problems.append(req)
            conditions.append(_condition(req))

    hz = plant.hazard(spec["hazard"])
    state_notes = []
    for tag in spec.get("related_tags", []):
        if tag in active_tags:
            barrier = next(b for b in hz["barriers"] if b["tag"] == tag)
            state_notes.append(f"Right now \"{barrier['name']}\" is weakened by an active change, "
                               "so a weaker part is riskier this month.")

    saving_row = next((r for r in rows if r["key"] == "price_inr"), None)
    saving = saving_row["note"] if saving_row else ""
    like_for_like = not problems
    if like_for_like:
        verdict = "Like-for-like on every safety-critical spec. OK to approve."
    else:
        verdict = ("Not like-for-like. Do not approve as is. Approve only if the supplier provides "
                   f"a model that is {', '.join(conditions)}.")
        if saving.startswith("Saves"):
            verdict += f" The {saving.split(' ', 1)[1]} saving doesn't cover the risk."

    return {
        "equipment": equipment_id,
        "equipment_name": plant.equipment[equipment_id]["name"],
        "safety_role": spec["safety_role"],
        "current_model": current.get("model") or spec["approved_model"],
        "proposed_model": proposed.get("model") or "Proposed part",
        "rows": rows,
        "like_for_like": like_for_like,
        "verdict": verdict,
        "plant_state": state_notes,
        "fail_count": sum(r["status"] == "fail" for r in rows),
        "missing_count": sum(r["status"] == "missing" for r in rows),
        "saving": saving,
    }


def _condition(req):
    rule = req["rule"]
    if rule == "min":
        return f"at least {req['value']:,} {req.get('unit', '')}".strip()
    if rule == "ex_gas_group":
        return "Ex-certified for gas group " + "/".join(req["value"])
    if rule == "temp_class":
        return f"{req['value']} or cooler"
    if rule == "spark_resistant":
        return "fitted with a spark-resistant impeller"
    return req["label"]


def voice_summary(report, asker_name):
    if report["like_for_like"]:
        return (f"{asker_name} wants to switch the {report['equipment_name']} to {report['proposed_model']}. "
                "It matches every safety-critical spec. I see no added risk. What should I tell "
                f"{asker_name}?")
    issues = []
    for r in report["rows"]:
        if r["status"] == "fail" and r["key"] == "airflow_m3h":
            issues.append("it moves less air")
        elif r["key"] == "ex_marking" and r["status"] in ("fail", "missing"):
            issues.append("it has no explosion-proof certificate")
        elif r["status"] == "fail" and r["key"] == "temperature_class":
            issues.append("its motor runs hotter than the zone allows")
        elif r["status"] == "fail" and r["key"] == "impeller_material":
            issues.append("its impeller can spark")
    saving = report["saving"]
    cheaper = f"It's {saving.split(' ', 1)[1]} cheaper, but " if saving.startswith("Saves") else "But "
    issue_text = ", ".join(issues[:-1]) + (" and " if len(issues) > 1 else "") + issues[-1] if issues else \
        "some safety specs are missing"
    return (f"{asker_name} wants to switch the {report['equipment_name']} to {report['proposed_model']}. "
            f"{cheaper}{issue_text}. I recommend rejecting unless the supplier fixes this. "
            f"What should I tell {asker_name}?")
