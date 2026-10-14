# Sanjaya

**A live voice agent that watches every change on the factory floor.**
AI Builder Camp 2026 · Track: Manufacturing: Intelligent Operations & Industrial Efficiency

Every industrial disaster is a stack of small changes that each looked fine. Sanjaya sees the stack
forming, asks the right person for a decision by voice, and watches the decision until it is safely done.

## What the prototype does

| Capability | What you see in the demo |
|---|---|
| **Watch** | Posts in the plant group (Hindi voice note, photo of a muted alarm, a trainee added to the night shift) are logged as changes. The dashboard's risk stack judges them *together*: 3 of 5 safeguards on the spray dryer weakened → critical alert, spoken to the plant head and safety officer. |
| **Approve** | "Boiler B-1 band karna hai" becomes a request card with a spoken evaluation that cites the plant's documented limit (20 min, SOP-R201-07 §4.2) and the changes already active. The approver answers by voice or button; Sanjaya **reads the decision back** before relaying it in Hindi, then runs a visible countdown with a reminder, an overrun warning, and escalation past the documented limit. No reply in 3 minutes → escalates to the next level. |
| **Evaluate** | Two fan datasheets → like-for-like check against the plant's requirements: airflow 12.5% short, no Ex certificate, T3 motor, mild-steel impeller → "not like-for-like, saves ₹60,000 but doesn't cover the risk". Also flags that the gas detector is already in maintenance. A nameplate photo of a fan installed without review raises an unreviewed-change alert and runs the same check. |

Safety rules enforced in code (`app/engine.py`): Sanjaya never approves or operates anything; every limit comes
from `data/plant_x.json` with its source, and if there is no documented limit it says so; every decision is read
back; non-approvers can't decide; everything is in the audit trail (`/api/audit`).

## How it is built

- **Backend:** FastAPI + WebSockets (`app/`), in-memory plant state, audit trail as JSONL.
- **Frontend:** mobile web app styled like a chat (`static/`), no install. Browser speech synthesis speaks voice
  notes only on the devices they're addressed to (Hindi or English per person); hold-to-talk records audio and
  also transcribes on the phone.
- **AI:** Gemini (`app/gemini.py`) reads text, photos, voice notes and datasheets into **schema-validated JSON**.
  Gemini only reads and classifies. Limits and pass/fail verdicts are deterministic code against the plant's
  documented data (`app/risk.py`, `app/parts.py`), so Sanjaya can't invent a safety number.
- **Scripted fallback:** if there's no Gemini key or a call fails, keyword rules (`app/fallback.py`) that understand
  the demo's English, Hinglish and Hindi take over, so the demo never dies on stage. The header shows
  "✨ Gemini live" or "Offline mode".
- **Data:** fictional Plant X (`data/plant_x.json`): people and roles, equipment, mini-HAZOP with safeguards,
  documented limits, part requirements; generated fan datasheets and demo photos (`scripts/make_demo_assets.py`).

## Run locally

```bash
pip install -r requirements-dev.txt
export GEMINI_API_KEY=...        # optional: without it Sanjaya runs in offline mode
uvicorn app.main:app --reload --port 8080
```

Open http://localhost:8080 on 2–3 devices (or browser windows): pick **Arjun** (operator), **Ravi** (plant head)
and **Dashboard**. Tap **Join shift** on each phone so it's allowed to play audio.

Tests: `pytest -q` (runs the whole demo script end to end in offline mode).

## Demo script

Open 🎬 on any phone. Each step posts as that person, so one presenter can drive the story; you can also do
any step for real by typing, holding the mic, or tapping the card buttons. Set the clock to 20× so the
15-minute countdown runs in about 45 seconds.

1. **Watch:** Arjun's voice note (batch raised to 480 kg) → Suresh's muted-alarm photo → trainee on the night shift → critical risk stack.
2. **Approve:** Arjun asks to shut down Boiler B-1 → Ravi's phone speaks the evaluation → Ravi says "Yes, but 15 minutes max" → read-back → Arjun hears the approval in Hindi → countdown → back on.
3. **Evaluate:** gas detector into maintenance → Priya asks to evaluate Supplier B's fan with both datasheets → report and voice summary to Ravi → then a nameplate photo shows the fan was swapped anyway.

## Deploy to Cloud Run

```bash
gcloud run deploy sanjaya --source . --region asia-south1 --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY=YOUR_KEY,SANJAYA_DEMO_SPEED=20 \
  --max-instances 1 --session-affinity --timeout 3600
```

`--max-instances 1` keeps everyone in the same in-memory chat; `--timeout 3600` keeps WebSockets open. Cloud Run
serves HTTPS, which phones require before they allow microphone access.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | none | Turns on Gemini. Without it, offline mode. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Any Gemini model that supports JSON schema output. |
| `SANJAYA_DEMO_SPEED` | `1` | Demo clock multiplier (also adjustable live in the 🎬 drawer). |
| `SANJAYA_ESCALATE_AFTER_MIN` | `3` | Plant minutes before an unanswered request escalates. |
| `SANJAYA_REMIND_BEFORE_MIN` | `5` | Plant minutes before the limit at which the requester is reminded. |

## Roadmap after the prototype

Probation monitoring of new parts (day-7 checks, linking related signals), WhatsApp chat-export import, drafting the
risk model from the plant's own HAZOP and SOPs with safety-officer review, and live temperature data for timers.

*All plant data, people, datasheets and photos are fictional.*
