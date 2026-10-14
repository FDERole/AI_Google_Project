"""Stack detection: judge every hazard against all active changes at once.

Each hazard is protected by several safeguards (barriers). An active change can
weaken a barrier. One weakened barrier is normal; several on the same hazard is
how disasters happen, so the level is driven by how many are weakened together.
"""

LEVELS = [
    (0, "normal", "All safeguards in place"),
    (1, "watch", "One safeguard weakened"),
    (2, "elevated", "Two safeguards weakened at once"),
    (3, "critical", "Three or more safeguards weakened at once"),
]


def level_for(count):
    for threshold, name, label in reversed(LEVELS):
        if count >= threshold:
            return {"rank": threshold, "name": name, "label": label}
    return {"rank": 0, "name": "normal", "label": LEVELS[0][2]}


def evaluate(plant, active_changes):
    """Return per-hazard stacks: which barriers are weakened and by which changes."""
    result = []
    for hz in plant.hazards:
        degraded = []
        for barrier in hz["barriers"]:
            causes = [c for c in active_changes if barrier["tag"] in c["tags"]]
            if causes:
                degraded.append({
                    "barrier": barrier["name"],
                    "barrier_id": barrier["id"],
                    "changes": [{"id": c["id"], "summary": c["summary"]} for c in causes],
                })
        lvl = level_for(len(degraded))
        result.append({
            "hazard_id": hz["id"],
            "hazard": hz["name"],
            "area": hz["area"],
            "source": hz["source"],
            "total_barriers": len(hz["barriers"]),
            "degraded": degraded,
            "barriers": [{"name": b["name"], "down": any(d["barrier_id"] == b["id"] for d in degraded)}
                         for b in hz["barriers"]],
            "level": lvl,
        })
    return result
