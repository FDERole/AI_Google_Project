"""End-to-end test of the demo script in offline (fallback) mode."""
import asyncio
import os

os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GOOGLE_API_KEY", None)

import pytest  # noqa: E402

from app import fallback, parts  # noqa: E402
from app.engine import Engine  # noqa: E402
from app.main import _demo_attachment  # noqa: E402
from app.plant import Plant  # noqa: E402


@pytest.fixture
def engine():
    e = Engine()
    e.brain.force_offline = True
    e.speed = 600  # one plant minute = 0.1 s
    return e


def run(coro):
    return asyncio.run(coro)


def last(engine, mtype):
    return next(m for m in reversed(engine.messages) if m["type"] == mtype)


def test_minutes_ignore_equipment_tags():
    assert fallback.find_minutes("Boiler B-1 shut down karna hai") is None
    assert fallback.find_minutes("Yes, but 15 minutes max") == 15
    assert fallback.find_minutes("haan, pandrah minute") == 15


def test_decisions():
    assert fallback.parse_decision("Yes, but 15 minutes max") == {
        "decision": "approve_with_conditions", "max_minutes": 15, "conditions": "maximum 15 minutes"}
    assert fallback.parse_decision("no more than 10 minutes")["max_minutes"] == 10
    assert fallback.parse_decision("No, not today")["decision"] == "reject"
    assert fallback.parse_decision("haan theek hai")["decision"] == "approve"
    assert fallback.parse_decision("hmm let me think")["decision"] == "unclear"


def test_interpret_demo_posts():
    plant = Plant()
    assert fallback.interpret("Aaj ka batch 400 se badhakar 480 kilo kar diya hai", plant)["tags"] == ["batch_size"]
    assert fallback.interpret("Night shift mein naya trainee Raju add kiya hai", plant)["tags"] == ["crew_training"]
    req = fallback.interpret("Plant X ka boiler B-1 shut down karna hai", plant)
    assert req["kind"] == "change_request" and req["equipment"] == "B-1"
    assert fallback.interpret("Shut down the boiler in Plant X.", plant)["kind"] == "change_request"
    assert fallback.interpret("Chai break 5 baje", plant)["kind"] == "chat"


def test_datasheet_extraction():
    a = fallback.extract_specs(fallback.pdf_text(_demo_attachment("datasheet:kestrel_kx120.pdf")["path"]))
    b = fallback.extract_specs(fallback.pdf_text(_demo_attachment("datasheet:brightline_bf105.pdf")["path"]))
    assert a == {"model": "Kestrel KX-120", "airflow_m3h": 12000, "ex_marking": "Ex db IIB T4 Gb",
                 "temperature_class": "T4", "impeller_material": "Spark-resistant cast aluminium",
                 "price_inr": 180000}
    assert b["model"] == "Brightline BF-105" and b["airflow_m3h"] == 10500
    assert b["ex_marking"] is None and b["temperature_class"] == "T3" and b["price_inr"] == 120000


def test_part_report_matches_concept_note():
    plant = Plant()
    cur = {"model": "Kestrel KX-120", "airflow_m3h": 12000, "ex_marking": "Ex db IIB T4 Gb",
           "temperature_class": "T4", "impeller_material": "Spark-resistant cast aluminium", "price_inr": 180000}
    new = {"model": "Brightline BF-105", "airflow_m3h": 10500, "ex_marking": None,
           "temperature_class": "T3", "impeller_material": "Mild steel", "price_inr": 120000}
    rep = parts.evaluate(plant, "EF-04", cur, new)
    notes = {r["key"]: r["note"] for r in rep["rows"]}
    assert notes["airflow_m3h"] == "Fails: 12.5% below required minimum"
    assert notes["ex_marking"] == "Missing: must be provided"
    assert notes["temperature_class"] == "Fails: runs hotter than the zone allows"
    assert notes["impeller_material"] == "Fails: spark risk in a solvent zone"
    assert notes["price_inr"] == "Saves ₹60,000"
    assert not rep["like_for_like"]
    assert parts.inr(180000) == "₹1,80,000"


def test_watch_stack_alert(engine):
    async def go():
        await engine.post("arjun", client_transcript="Aaj ka batch 400 se badhakar 480 kilo kar diya hai", as_voice=True)
        await engine.post("suresh", "Alarm baar baar baj raha tha, mute kar diya",
                          [_demo_attachment("demo:alarm_panel_muted.png")])
        await engine.post("suresh", "Night shift mein naya trainee Raju add kiya hai, first day hai")
    run(go())
    h1 = next(s for s in engine.snapshot()["risk"] if s["hazard_id"] == "H1")
    assert h1["level"]["name"] == "critical" and len(h1["degraded"]) == 3
    alerts = [m for m in engine.messages if m["type"] == "alert"]
    assert any("CRITICAL" in a["text"] and "spray dryer SD-1" in a["text"] for a in alerts)
    crit = next(a for a in alerts if "CRITICAL" in a["text"])
    assert "TAH-301" in crit["text"]  # recommends restoring the alarm first
    assert set(crit["speak"][0]["to"]) == {"ravi", "meena"}


def test_approval_loop_with_readback_and_timer(engine):
    async def go():
        await engine.post("arjun", "Plant X ka boiler B-1 shut down karna hai, maintenance ke liye")
        req = next(iter(engine.requests.values()))
        card = last(engine, "request_card")
        assert "20 minutes" in card["text"] and "SOP-R201-07" in card["text"]
        assert card["speak"][0]["to"] == ["ravi"]
        # Ravi answers by voice; Sanjaya reads it back before relaying.
        await engine.post("ravi", client_transcript="Yes, but 15 minutes max", as_voice=True)
        assert req["status"] == "awaiting_readback"
        assert last(engine, "readback_card")["text"] == "Confirming: approved, maximum 15 minutes. Correct?"
        await engine.post("ravi", "yes correct")
        assert req["status"] == "approved" and req["max_minutes"] == 15
        relay = last(engine, "relay_card")
        assert "Ravi ne approve kiya" in relay["text"] and relay["speak"][0]["lang"] == "hi-IN"
        await engine.post("arjun", "Boiler band kar diya")
        assert req["status"] == "active"
        await asyncio.sleep(16 * 60 / engine.speed + 0.5)  # past the 15-minute approval
        assert req["status"] == "overrun"
        await engine.post("arjun", "Boiler wapas chalu kar diya")
        assert req["status"] == "done"
    run(go())
    events = [a["event"] for a in engine.audit]
    for e in ("request_created", "decision_heard", "decision_confirmed", "change_started",
              "timer_reminder", "timer_overrun", "change_finished"):
        assert e in events


def test_readback_warns_over_documented_limit_and_correction(engine):
    async def go():
        await engine.post("arjun", "Can I shut down the boiler?")
        req = next(iter(engine.requests.values()))
        await engine.decide(req, "ravi", {"decision": "approve_with_conditions", "max_minutes": 50})
        assert "more than the documented 20-minute limit" in req["readback_text"]
        await engine.post("ravi", "no, galat")  # misheard: correct it
        assert req["status"] == "pending"
        await engine.decide(req, "ravi", {"decision": "approve_with_conditions", "max_minutes": 15})
        await engine.confirm(req, "ravi", True)
        assert req["max_minutes"] == 15
    run(go())


def test_no_documented_limit_is_admitted(engine):
    async def go():
        await engine.post("arjun", "Can I shut down the reactor R-201?")
    run(go())
    assert "I don't know the safe shutdown time for Reactor R-201" in last(engine, "request_card")["text"]


def test_sanjaya_never_lets_non_approvers_decide(engine):
    async def go():
        await engine.post("arjun", "Can I shut down the boiler?")
        req = next(iter(engine.requests.values()))
        await engine.decide(req, "arjun", {"decision": "approve"})
        assert req["status"] == "pending"
        await engine.skip_wait(req["id"])
        assert req["approvers"] == ["vikram"] and req["level"] == 2
    run(go())


def test_part_evaluation_case1_and_case2(engine):
    async def go():
        await engine.post("suresh", "Gas detector GD-07 calibration ke liye maintenance mein hai")
        await engine.post("priya", "We're planning to switch to Supplier B for the fan. Go through the attached "
                                   "docs and evaluate the risk.",
                          [_demo_attachment("datasheet:kestrel_kx120.pdf"),
                           _demo_attachment("datasheet:brightline_bf105.pdf")])
        report = last(engine, "report_card")["data"]["report"]
        assert report["proposed_model"] == "Brightline BF-105" and report["fail_count"] == 3
        assert report["plant_state"]  # gas detector already in maintenance
        card = last(engine, "request_card")
        assert "60,000 cheaper" in card["text"] and "explosion-proof" in card["text"]
        req = engine.requests[card["data"]["request"]["id"]]
        await engine.decide(req, "ravi", {"decision": "reject"})
        await engine.confirm(req, "ravi", True)
        assert req["status"] == "rejected"
        # Case 2: someone installs the fan anyway and posts the nameplate.
        await engine.post("arjun", "Solvent room ka fan badal diya", [_demo_attachment("demo:fan_nameplate_bf105.png")])
        unrev = last(engine, "report_card")["data"]["report"]
        assert unrev.get("unreviewed") and not unrev["like_for_like"]
        assert any(c["kind"] == "unreviewed" for c in engine.active_changes())
    run(go())
