"""Sanjaya's engine: the plant group chat, the change log, the approval loop and timers.

Safety rules enforced here (from the concept note):
- Sanjaya never approves anything itself and never operates equipment.
- Every limit it quotes comes from the plant's documented data, with its source.
  If it has no documented limit, it says so.
- Every decision is read back and confirmed before it is relayed.
- No reply within the escalation window sends the request to the next level.
- Everything is written to the audit trail.
"""
import asyncio
import itertools
import json
import logging
import re
import time

from . import fallback, parts, risk
from .brain import Brain
from .config import DATA_DIR, ESCALATE_AFTER_MIN, REMIND_BEFORE_MIN, RUNTIME_DIR, DEMO_SPEED
from .plant import Plant

log = logging.getLogger("sanjaya.engine")

# Which weakened safeguard to suggest restoring first: quick, reversible fixes before slow ones.
RESTORE_PRIORITY = ["alarm", "nitrogen", "gas_detector", "fan", "hot_work", "batch_size", "crew_training"]

# Seconds of real time an approver gets before escalation, even when the demo clock is sped up.
MIN_ESCALATION_SECONDS = 45


def now_ms():
    return int(time.time() * 1000)


def _lc(text):
    """Lowercase only the first letter, so equipment tags like TAH-301 stay readable."""
    return text[:1].lower() + text[1:]


def norm_model(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


class Engine:
    def __init__(self):
        self.plant = Plant()
        self.brain = Brain(self.plant)
        self.speed = DEMO_SPEED
        self.clients = {}
        self.library = json.loads((DATA_DIR / "datasheets" / "index.json").read_text(encoding="utf-8"))
        self.library.pop("_note", None)
        self.tasks = set()
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        self.reset()

    # ---- state ---------------------------------------------------------------

    def reset(self):
        for task in getattr(self, "tasks", set()):
            task.cancel()
        self.tasks = set()
        self._ids = itertools.count(1)
        self.messages = []
        self.changes = []
        self.requests = {}
        self.audit = []
        self.last_levels = {h["id"]: 0 for h in self.plant.hazards}
        self.messages.append(self._msg(
            "sanjaya", "text",
            f"Namaste {self.plant.info['group_name']}! I'm Sanjaya. I watch every change posted here, "
            "ask the right person for decisions by voice, and keep watch until changes are safely done. "
            "I never approve anything myself and never operate equipment.",
        ))

    def _id(self, prefix):
        return f"{prefix}{next(self._ids)}"

    def _msg(self, author, mtype, text="", data=None, media=None, transcript=None, speak=None, mode=None):
        return {
            "id": self._id("m"), "at": now_ms(), "author": author, "author_name": self.plant.name(author),
            "type": mtype, "text": text, "data": data or {}, "media": media or [],
            "transcript": transcript, "speak": speak or [], "mode": mode,
        }

    def _speak(self, user_ids, en, hi=None):
        """Voice-note instructions grouped by language. Clients only play entries addressed to them."""
        by_lang = {}
        for uid in user_ids:
            user = self.plant.user(uid)
            lang = user["lang"] if user else "en-IN"
            if lang == "hi-IN" and not hi:
                lang = "en-IN"
            by_lang.setdefault(lang, []).append(uid)
        return [{"to": ids, "lang": lang, "text": hi if lang == "hi-IN" else en} for lang, ids in by_lang.items()]

    def _text_for(self, user_id, en, hi=None):
        user = self.plant.user(user_id)
        return hi if (hi and user and user["lang"] == "hi-IN") else en

    def real_seconds(self, plant_minutes):
        return plant_minutes * 60 / self.speed

    def _log(self, event, **detail):
        entry = {"at": now_ms(), "event": event, **detail}
        self.audit.append(entry)
        try:
            with open(RUNTIME_DIR / "audit.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def active_changes(self):
        return [c for c in self.changes if c["status"] == "active"]

    def active_tags(self):
        return {t for c in self.active_changes() for t in c["tags"]}

    def snapshot(self):
        return {
            "now": now_ms(),
            "mode": self.brain.mode,
            "speed": self.speed,
            "risk": risk.evaluate(self.plant, self.active_changes()),
            "changes": list(reversed(self.changes))[:30],
            "requests": [self._request_view(r) for r in reversed(list(self.requests.values()))],
            "audit": list(reversed(self.audit))[:60],
        }

    # ---- websocket fan-out --------------------------------------------------

    async def emit(self, event):
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.pop(ws, None)

    async def add_message(self, msg):
        self.messages.append(msg)
        self._log("message", id=msg["id"], author=msg["author"], type=msg["type"],
                  text=msg["text"], transcript=msg["transcript"],
                  media=[m["url"] for m in msg["media"]])
        await self.emit({"type": "message", "message": msg})

    async def update_message(self, msg):
        await self.emit({"type": "message_update", "message": msg})

    async def push_dashboard(self):
        await self.emit({"type": "dashboard", "dashboard": self.snapshot()})

    def _find_msg(self, msg_id):
        return next((m for m in self.messages if m["id"] == msg_id), None)

    # ---- inbound posts ------------------------------------------------------

    async def post(self, author, text="", attachments=(), client_transcript=None, reply_to=None, as_voice=False):
        """as_voice: a voice note already transcribed on the phone (browser speech recognition)."""
        attachments = list(attachments)
        kinds = {a["kind"] for a in attachments}
        mtype = "voice" if ("voice" in kinds or as_voice) else "photo" if "photo" in kinds else \
            "file" if "document" in kinds else "text"
        transcript, mode = None, None
        if "voice" in kinds:
            transcript, mode = await asyncio.to_thread(self.brain.transcribe, attachments, client_transcript)
            transcript = transcript or client_transcript
        elif as_voice:
            transcript = client_transcript or text
            text = ""
        media = [{"kind": a["kind"], "url": a["url"], "name": a.get("name")} for a in attachments]
        msg = self._msg(author, mtype, text, data={"reply_to": reply_to}, media=media,
                        transcript=transcript, mode=mode)
        await self.add_message(msg)
        try:
            await self.handle(msg, attachments)
        finally:
            await self.push_dashboard()
        return msg

    async def handle(self, msg, attachments):
        author = msg["author"]
        text = " ".join(t for t in (msg["text"], msg["transcript"]) if t)
        reply_to = msg["data"].get("reply_to")
        voice = [a for a in attachments if a["kind"] == "voice"]

        req = self._awaiting_readback_for(author, reply_to)
        if req:
            answer, _ = await asyncio.to_thread(self.brain.parse_confirmation, text, req["readback_text"], voice)
            if answer != "unclear":
                await self.confirm(req, author, answer == "yes", via="voice" if voice else "text")
                return

        req = self._pending_for_approver(author, reply_to)
        if req:
            decision, mode = await asyncio.to_thread(self.brain.parse_decision, text, req["summary"], voice)
            if decision["decision"] != "unclear":
                await self.decide(req, author, decision, via="voice" if voice else "text")
                return

        req = self._requester_open_request(author)
        if req and req["status"] == "approved" and fallback.is_started(text):
            await self.start(req, author)
            return
        if req and req["status"] in ("active", "overrun") and fallback.is_finished(text):
            await self.finish(req, author)
            return

        if msg["type"] == "voice" and not text.strip():
            sorry = "I couldn't hear that voice note clearly. Please try again, type it, or use the buttons."
            await self.add_message(self._msg("sanjaya", "text", sorry, speak=self._speak([author], sorry)))
            return

        interp, mode = await asyncio.to_thread(self.brain.interpret, text, author, attachments)
        kind = interp["kind"]
        if kind == "routine_change" and interp["tags"]:
            await self.record_change(msg, interp, mode)
        elif kind == "change_request" and interp.get("equipment"):
            await self.create_request(msg, interp, mode)
        elif kind == "part_evaluation":
            await self.evaluate_part(msg, interp, attachments, mode)
        elif kind == "unreviewed_part_change":
            await self.unreviewed_part(msg, interp, attachments, mode)
        elif kind == "started" and req and req["status"] == "approved":
            await self.start(req, author)
        elif kind == "finished" and req and req["status"] in ("active", "overrun"):
            await self.finish(req, author)
        elif interp.get("seen"):
            msg["data"]["seen"] = interp["seen"]
            await self.update_message(msg)

    def _awaiting_readback_for(self, user, reply_to):
        cands = [r for r in self.requests.values() if r["status"] == "awaiting_readback" and r["decider"] == user]
        return self._pick(cands, reply_to)

    def _pending_for_approver(self, user, reply_to):
        cands = [r for r in self.requests.values() if r["status"] == "pending" and user in r["approvers"]]
        return self._pick(cands, reply_to)

    def _requester_open_request(self, user):
        cands = [r for r in self.requests.values()
                 if r["requester"] == user and r["kind"] == "equipment"
                 and r["status"] in ("approved", "active", "overrun")]
        return cands[-1] if cands else None

    @staticmethod
    def _pick(cands, reply_to):
        if reply_to:
            for r in cands:
                if reply_to in (r["id"], r.get("card_msg_id"), r.get("readback_msg_id")):
                    return r
        return cands[-1] if cands else None

    # ---- WATCH: routine changes and the risk stack -------------------------

    async def record_change(self, msg, interp, mode, kind="routine"):
        change = {
            "id": self._id("c"), "kind": kind, "tags": interp["tags"], "summary": interp["summary"],
            "equipment": interp.get("equipment"), "by": msg["author"], "by_name": self.plant.name(msg["author"]),
            "at": now_ms(), "status": "active", "msg_id": msg["id"],
        }
        self.changes.append(change)
        msg["data"]["change"] = {"id": change["id"], "summary": change["summary"], "kind": kind}
        if interp.get("seen"):
            msg["data"]["seen"] = interp["seen"]
        msg["mode"] = msg["mode"] or mode
        self._log("change_logged", change=change["id"], summary=change["summary"], tags=change["tags"], mode=mode)
        await self.update_message(msg)
        await self.check_stacks()
        return change

    async def check_stacks(self):
        for stack in risk.evaluate(self.plant, self.active_changes()):
            rank, before = stack["level"]["rank"], self.last_levels[stack["hazard_id"]]
            self.last_levels[stack["hazard_id"]] = rank
            if rank > before and rank >= 2:
                await self.stack_alert(stack)

    def _sync_levels(self):
        """After a change closes, lower the remembered levels so a later rise alerts again."""
        for stack in risk.evaluate(self.plant, self.active_changes()):
            self.last_levels[stack["hazard_id"]] = stack["level"]["rank"]

    async def stack_alert(self, stack):
        degraded = stack["degraded"]
        listing = "; ".join(f"{d['barrier']} ({_lc(d['changes'][-1]['summary'])})" for d in degraded)
        restore = sorted(degraded, key=lambda d: next(
            (i for i, key in enumerate(RESTORE_PRIORITY) if key in d["barrier"].lower().replace(" ", "_")
             or key.replace("_", " ") in d["barrier"].lower()), len(RESTORE_PRIORITY)))[0]
        n, total = len(degraded), stack["total_barriers"]
        if stack["level"]["name"] == "critical":
            text = (f"⚠️ Risk stack CRITICAL: {stack['hazard']}. {n} of {total} safeguards are weakened right now: "
                    f"{listing}. Each change looked fine on its own; together they stack up. "
                    f"Recommend restoring \"{restore['barrier']}\" before continuing.")
            spoken = (f"Warning. {stack['hazard']}. {n} of {total} safeguards are weakened at the same time. "
                      f"Each change looked fine on its own. I recommend restoring {restore['barrier']} before continuing.")
        else:
            text = (f"Heads-up: two safeguards on {stack['hazard']} are weakened at the same time: {listing}. "
                    "One more change would make this critical.")
            spoken = f"Heads up. Two safeguards on {stack['hazard']} are weakened at the same time."
        watchers = self.plant.risk_watchers()
        msg = self._msg("sanjaya", "alert", text, data={"stack": stack}, speak=self._speak(watchers, spoken))
        self._log("risk_alert", hazard=stack["hazard_id"], level=stack["level"]["name"], weakened=n)
        await self.add_message(msg)

    # ---- APPROVE: change requests ------------------------------------------

    def _tags_for_equipment(self, eq_id):
        return sorted({b["tag"] for h in self.plant.hazards for b in h["barriers"]
                       if b["tag"].rsplit("_", 1)[-1] == eq_id})

    async def create_request(self, msg, interp, mode):
        eq_id, action = interp["equipment"], interp.get("action") or "shutdown"
        eq = self.plant.equipment[eq_id]
        requester = msg["author"]
        limit = self.plant.find_limit(eq_id, action)
        eq_tags = self._tags_for_equipment(eq_id)

        lines = [f"{self.plant.name(requester)} has asked to {action.replace('shutdown', 'shut down')} "
                 f"{eq['name']} in {self.plant.info['name']}."]
        if limit:
            lines.append(f"If it's off for more than {limit['max_minutes']} minutes {limit['condition']}, "
                         f"{limit['consequence_en']} ({limit['source']}), so it must be monitored.")
        else:
            lines.append(f"I don't know the safe {action} time for {eq['name']}. Please check before approving.")
        stack_lines = []
        active = self.active_changes()
        for stack in risk.evaluate(self.plant, active):
            hz = self.plant.hazard(stack["hazard_id"])
            if not any(b["tag"] in eq_tags for b in hz["barriers"]):
                continue
            if stack["degraded"]:
                others = ", ".join(_lc(c["summary"]) for d in stack["degraded"] for c in d["changes"])
                stack_lines.append(f"Also active right now on {hz['name']}: {others}. Approving makes "
                                   f"{len(stack['degraded']) + 1} of {stack['total_barriers']} safeguards weakened.")
        lines += stack_lines
        lines.append(f"What shall I tell {self.plant.name(requester)}?")
        evaluation = " ".join(lines)

        req = {
            "id": self._id("r"), "kind": "equipment", "requester": requester, "msg_id": msg["id"],
            "equipment": eq_id, "action": action, "tags": eq_tags,
            "summary": f"{action.replace('shutdown', 'Shut down')} {eq['name']}",
            "limit": limit, "evaluation": evaluation, "stack_notes": stack_lines,
            "level": 1, "approvers": self.plant.approvers(1), "status": "pending",
            "decision": None, "max_minutes": None, "decider": None, "created_at": now_ms(),
            "requested_minutes": interp.get("requested_minutes"), "escalations": [],
        }
        self.requests[req["id"]] = req
        msg["data"]["request"] = req["id"]
        msg["mode"] = msg["mode"] or mode
        await self.update_message(msg)
        self._log("request_created", request=req["id"], summary=req["summary"], limit=limit and limit["id"], mode=mode)
        await self._post_request_card(req)
        hi = f"{self.plant.name(requester)}, aapki request {self._names(req['approvers'])} ko bhej di hai. Jawab aate hi bataunga."
        en = f"{self.plant.name(requester)}, I've sent your request to {self._names(req['approvers'])}. I'll tell you as soon as they answer."
        await self.add_message(self._msg("sanjaya", "text", self._text_for(requester, en, hi),
                                         speak=self._speak([requester], en, hi)))
        self._spawn(self._escalation_watch(req["id"], req["level"]))

    def _names(self, ids):
        names = [self.plant.name(i) for i in ids]
        return " and ".join(names)

    async def _post_request_card(self, req):
        card = self._msg("sanjaya", "request_card", req["evaluation"], data={"request": self._request_view(req)},
                         speak=self._speak(req["approvers"], req["evaluation"]))
        req["card_msg_id"] = card["id"]
        await self.add_message(card)

    async def _refresh_card(self, req):
        card = self._find_msg(req.get("card_msg_id"))
        if card:
            card["data"]["request"] = self._request_view(req)
            await self.update_message(card)

    def _request_view(self, req):
        view = {k: v for k, v in req.items() if k not in ("report",)}
        view["requester_name"] = self.plant.name(req["requester"])
        view["approver_names"] = [self.plant.name(a) for a in req["approvers"]]
        view["decider_name"] = self.plant.name(req["decider"]) if req.get("decider") else None
        if req.get("report"):
            view["report"] = req["report"]
        return view

    async def _escalation_watch(self, req_id, level):
        await asyncio.sleep(max(MIN_ESCALATION_SECONDS, self.real_seconds(ESCALATE_AFTER_MIN)))
        req = self.requests.get(req_id)
        if req and req["status"] == "pending" and req["level"] == level:
            await self.escalate(req)

    async def escalate(self, req):
        old = req["approvers"]
        if req["level"] >= self.plant.max_approver_level():
            text = (f"No approver has answered the request \"{req['summary']}\". "
                    f"{self.plant.name(req['requester'])}: do NOT proceed until someone approves.")
            hi = f"{self.plant.name(req['requester'])}, abhi tak kisi ne approve nahi kiya. Kripya aage mat badhiye."
            await self.add_message(self._msg("sanjaya", "alert", text,
                                             speak=self._speak([req["requester"]], text, hi)))
            self._log("request_unanswered", request=req["id"])
            return
        req["level"] += 1
        req["approvers"] = self.plant.approvers(req["level"])
        req["escalations"].append({"at": now_ms(), "from": old, "to": req["approvers"]})
        text = (f"No reply from {self._names(old)} in {ESCALATE_AFTER_MIN:g} minutes. "
                f"Escalating to {self._names(req['approvers'])}.")
        self._log("request_escalated", request=req["id"], to=req["approvers"])
        await self.add_message(self._msg("sanjaya", "text", text))
        await self._refresh_card(req)
        spoken = f"Escalated to you. {req['evaluation']}"
        await self.add_message(self._msg("sanjaya", "text", f"🔔 {self._names(req['approvers'])}: please decide.",
                                         data={"reply_to": req["card_msg_id"]},
                                         speak=self._speak(req["approvers"], spoken)))
        self._spawn(self._escalation_watch(req["id"], req["level"]))

    async def decide(self, req, approver, decision, via="button"):
        if req["status"] != "pending" or approver not in req["approvers"]:
            return
        kind = decision["decision"]
        minutes = decision.get("max_minutes")
        limit = req.get("limit")
        warning = ""
        if req["kind"] == "part":
            minutes = None
            if kind == "reject":
                readback = "Confirming: rejected. Correct?"
            else:
                cond = f" with conditions: {decision['conditions']}" if decision.get("conditions") else ""
                readback = f"Confirming: approved{cond}. Correct?"
                report = req.get("report") or {}
                if report and not report.get("like_for_like"):
                    warning = (f"Note: I found {report['fail_count']} failing and {report['missing_count']} "
                               "missing safety specs on this part. ")
        elif kind == "reject":
            readback = "Confirming: rejected. Correct?"
        else:
            if minutes is None and limit:
                minutes = limit["max_minutes"]
                readback = f"Confirming: approved, within the documented {minutes}-minute limit. Correct?"
            elif minutes is None:
                readback = "Confirming: approved, with no time limit. Correct?"
            else:
                readback = f"Confirming: approved, maximum {minutes} minutes. Correct?"
            if limit and minutes and minutes > limit["max_minutes"]:
                warning = (f"Note: {minutes} minutes is more than the documented {limit['max_minutes']}-minute "
                           f"limit ({limit['source']}). ")
        req.update(status="awaiting_readback", decider=approver,
                   pending_decision={**decision, "max_minutes": minutes}, readback_text=warning + readback)
        self._log("decision_heard", request=req["id"], by=approver, via=via, decision=kind, max_minutes=minutes)
        card = self._msg("sanjaya", "readback_card", warning + readback,
                         data={"request_id": req["id"], "decider": approver, "reply_to": req.get("card_msg_id")},
                         speak=self._speak([approver], warning + readback))
        req["readback_msg_id"] = card["id"]
        await self.add_message(card)
        await self._refresh_card(req)

    async def confirm(self, req, user, yes, via="button"):
        if req["status"] != "awaiting_readback" or user != req["decider"]:
            return
        rb = self._find_msg(req.get("readback_msg_id"))
        if not yes:
            req.update(status="pending", decider=None, pending_decision=None)
            if rb:
                rb["data"]["resolved"] = "corrected"
                await self.update_message(rb)
            self._log("readback_corrected", request=req["id"], by=user)
            text = "Okay, I won't relay that. Please tell me your decision again."
            await self.add_message(self._msg("sanjaya", "text", text, speak=self._speak([user], text)))
            await self._refresh_card(req)
            return
        d = req["pending_decision"]
        approved = d["decision"] != "reject"
        req.update(status="approved" if approved else "rejected", decision=d["decision"],
                   max_minutes=d.get("max_minutes"), conditions=d.get("conditions"), decided_at=now_ms())
        if rb:
            rb["data"]["resolved"] = "confirmed"
            await self.update_message(rb)
        self._log("decision_confirmed", request=req["id"], by=user, via=via, decision=d["decision"],
                  max_minutes=req["max_minutes"])
        await self._refresh_card(req)
        await self._relay(req)
        if req["kind"] == "part" and approved:
            req["status"] = "done"
            await self._refresh_card(req)

    async def _relay(self, req):
        who, by = req["requester"], self.plant.name(req["decider"])
        name = self.plant.equipment[req["equipment"]]["name"]
        if req["kind"] == "part":
            if req["status"] == "rejected":
                en = f"Rejected by {by}. Don't switch the {name} to {req['report']['proposed_model']}."
            else:
                cond = f" Conditions: {req['conditions']}." if req.get("conditions") else ""
                en = f"Approved by {by}: switch the {name} to {req['report']['proposed_model']}.{cond}"
            hi = None
        elif req["status"] == "rejected":
            en = f"Rejected by {by}. Do not {req['action'].replace('shutdown', 'shut down')} {name}."
            hi = f"{by} ne mana kiya hai. {name} band mat kijiye."
        else:
            m = req["max_minutes"]
            if m:
                en = f"Approved by {by}. {name} shutdown allowed for {m} minutes maximum. Tell me when you start."
                hi = f"{by} ne approve kiya. {name} sirf {m} minute tak band kar sakte hain. Shuru karte hi mujhe batayein."
            else:
                en = f"Approved by {by}. Tell me when you start."
                hi = f"{by} ne approve kiya. Shuru karte hi mujhe batayein."
        text = self._text_for(who, en, hi)
        relay = self._msg("sanjaya", "relay_card", text,
                          data={"request_id": req["id"], "requester": who, "approved": req["status"] != "rejected",
                                "kind": req["kind"], "english": en if text != en else None},
                          speak=self._speak([who], en, hi))
        req["relay_msg_id"] = relay["id"]
        await self.add_message(relay)

    # ---- enforce the condition: countdown ---------------------------------

    async def start(self, req, user):
        if req["status"] != "approved" or user != req["requester"]:
            return
        m = req["max_minutes"]
        name = self.plant.equipment[req["equipment"]]["name"]
        req.update(status="active", started_at=now_ms())
        req["ends_at"] = req["started_at"] + int(self.real_seconds(m) * 1000) if m else None
        change = {
            "id": self._id("c"), "kind": "approved", "tags": req["tags"],
            "summary": f"{name} shut down (approved by {self.plant.name(req['decider'])}"
                       + (f", max {m} min)" if m else ")"),
            "equipment": req["equipment"], "by": user, "by_name": self.plant.name(user),
            "at": now_ms(), "status": "active", "msg_id": req["msg_id"], "request": req["id"],
        }
        self.changes.append(change)
        req["change_id"] = change["id"]
        self._log("change_started", request=req["id"], max_minutes=m)
        timer = self._msg("sanjaya", "timer_card", f"{name}: shutdown in progress",
                          data={"request_id": req["id"], "started_at": req["started_at"], "ends_at": req["ends_at"],
                                "max_minutes": m, "speed": self.speed, "status": "running",
                                "requester": user, "approver": req["decider"]})
        req["timer_msg_id"] = timer["id"]
        await self.add_message(timer)
        if m:
            remind = max(m - REMIND_BEFORE_MIN, 0)
            en = f"Okay. {m}-minute countdown started." + (f" I'll remind you at {remind:g} minutes." if remind else "")
            hi = f"Theek hai. {m} minute ka timer shuru." + (f" {remind:g} minute par yaad dilaunga." if remind else "")
            await self.add_message(self._msg("sanjaya", "text", self._text_for(user, en, hi),
                                             speak=self._speak([user], en, hi)))
            self._spawn(self._timer(req["id"]))
        await self.check_stacks()
        await self._refresh_card(req)

    async def _timer(self, req_id):
        req = self.requests[req_id]
        m = req["max_minutes"]
        name = self.plant.equipment[req["equipment"]]["name"]
        who, approver = req["requester"], req["decider"]
        remind = m - REMIND_BEFORE_MIN
        if remind > 0:
            await asyncio.sleep(self.real_seconds(remind))
            if req["status"] != "active":
                return
            en = f"{remind:g} minutes done. {REMIND_BEFORE_MIN:g} minutes left. Get ready to bring {name} back on."
            hi = f"{remind:g} minute ho gaye. {REMIND_BEFORE_MIN:g} minute baaki hain. {name} wapas chalu karne ki taiyari kijiye."
            await self.add_message(self._msg("sanjaya", "text", self._text_for(who, en, hi),
                                             speak=self._speak([who], en, hi)))
            self._log("timer_reminder", request=req_id)
            await asyncio.sleep(self.real_seconds(REMIND_BEFORE_MIN))
        else:
            await asyncio.sleep(self.real_seconds(m))
        if req["status"] != "active":
            return
        req["status"] = "overrun"
        en_who = f"Time's up! {m} minutes are over. Bring {name} back on now and tell me."
        hi_who = f"Samay khatam! {m} minute ho gaye. {name} turant wapas chalu kijiye aur mujhe batayein."
        en_appr = (f"Time's up: {name} has been off for {m} minutes, the maximum you approved. "
                   f"{self.plant.name(who)} has not confirmed it's back on.")
        speak = self._speak([who], en_who, hi_who) + self._speak([approver], en_appr)
        await self.add_message(self._msg("sanjaya", "alert", f"⏰ {en_appr}", speak=speak))
        self._log("timer_overrun", request=req_id)
        await self._set_timer_status(req, "overrun")
        await self._refresh_card(req)
        limit = req.get("limit")
        if limit and limit["max_minutes"] > m:
            await asyncio.sleep(self.real_seconds(limit["max_minutes"] - m))
            if req["status"] != "overrun":
                return
            top = self.plant.approvers(self.plant.max_approver_level())
            text = (f"🚨 {name} is now past the documented {limit['max_minutes']}-minute limit "
                    f"({limit['source']}): {limit['consequence_en']}. Escalating to {self._names(top)}.")
            await self.add_message(self._msg("sanjaya", "alert", text,
                                             speak=self._speak(sorted(set(top + [approver])), text)))
            self._log("limit_breached", request=req_id, limit=limit["id"])

    async def _set_timer_status(self, req, status, extra=None):
        timer = self._find_msg(req.get("timer_msg_id"))
        if timer:
            timer["data"]["status"] = status
            timer["data"].update(extra or {})
            await self.update_message(timer)

    async def finish(self, req, user):
        if req["status"] not in ("active", "overrun"):
            return
        overran = req["status"] == "overrun"
        req.update(status="done", finished_at=now_ms())
        elapsed = (req["finished_at"] - req["started_at"]) / 1000 * self.speed / 60
        for c in self.changes:
            if c["id"] == req.get("change_id"):
                c["status"] = "closed"
        name = self.plant.equipment[req["equipment"]]["name"]
        m = req["max_minutes"]
        within = (f"within the {m}-minute limit" if m and elapsed <= m else
                  f"over the {m}-minute limit" if m else "")
        en = f"Thanks. {name} back on after {elapsed:.0f} minutes, {within}. Logged."
        hi = f"Shukriya. {name} {elapsed:.0f} minute baad wapas chalu. Log kar liya."
        speak = self._speak([user], en, hi) + self._speak([req["decider"]], en)
        await self.add_message(self._msg("sanjaya", "text", self._text_for(user, en, hi), speak=speak))
        self._log("change_finished", request=req["id"], elapsed_minutes=round(elapsed, 1), overran=overran)
        await self._set_timer_status(req, "done", {"finished_at": req["finished_at"],
                                                   "elapsed_minutes": round(elapsed, 1)})
        self._sync_levels()
        await self._refresh_card(req)

    # ---- EVALUATE: replacement parts ---------------------------------------

    def _library_specs(self, model):
        entry = next((v for k, v in self.library.items() if norm_model(k) == norm_model(model)), None)
        if not entry:
            return None
        path = DATA_DIR / "datasheets" / entry["file"]
        specs, _ = self.brain.extract_specs({"kind": "document", "path": path, "mime": "application/pdf"})
        return specs

    async def _read_specs(self, eq_id, attachments, seen_model=None):
        approved = self.plant.part_requirements[eq_id]["approved_model"]
        extracted = []
        for att in attachments:
            if att["kind"] in ("document", "photo"):
                specs, mode = await asyncio.to_thread(self.brain.extract_specs, att)
                extracted.append(specs)
        current = next((s for s in extracted if s.get("model") and
                        norm_model(approved).endswith(norm_model(s["model"].split()[-1]))), None)
        proposed = next((s for s in extracted if s is not current and s.get("model")), None)
        if current is None:
            current = await asyncio.to_thread(self._library_specs, approved) or {"model": approved}
        if (proposed is None or not any(v for k, v in proposed.items() if k != "model")) and seen_model:
            proposed = await asyncio.to_thread(self._library_specs, seen_model) or proposed
        return current, proposed

    async def evaluate_part(self, msg, interp, attachments, mode):
        eq_id = interp.get("equipment") if interp.get("equipment") in self.plant.part_requirements else "EF-04"
        asker = msg["author"]
        current, proposed = await self._read_specs(eq_id, attachments, interp.get("model"))
        if not proposed:
            text = ("Please attach the new supplier's datasheet (and the current one if you have it). "
                    "I won't evaluate a part from its name alone.")
            await self.add_message(self._msg("sanjaya", "text", text, speak=self._speak([asker], text)))
            return
        report = parts.evaluate(self.plant, eq_id, current, proposed, self.active_tags())
        voice = parts.voice_summary(report, self.plant.name(asker))
        req = {
            "id": self._id("r"), "kind": "part", "requester": asker, "msg_id": msg["id"], "equipment": eq_id,
            "action": "replace", "tags": [], "summary": f"Switch {report['equipment_name']} to {report['proposed_model']}",
            "limit": None, "evaluation": voice, "stack_notes": report["plant_state"], "level": 1,
            "approvers": self.plant.approvers(1), "status": "pending", "decision": None, "max_minutes": None,
            "decider": None, "created_at": now_ms(), "escalations": [], "report": report,
        }
        self.requests[req["id"]] = req
        self._log("part_evaluated", request=req["id"], proposed=report["proposed_model"],
                  like_for_like=report["like_for_like"], fails=report["fail_count"],
                  missing=report["missing_count"], mode=mode)
        await self.add_message(self._msg("sanjaya", "report_card", report["verdict"],
                                         data={"report": report, "request_id": req["id"]}))
        await self._post_request_card(req)
        self._spawn(self._escalation_watch(req["id"], req["level"]))

    async def unreviewed_part(self, msg, interp, attachments, mode):
        eq_id = interp.get("equipment") if interp.get("equipment") in self.plant.part_requirements else "EF-04"
        name = self.plant.equipment[eq_id]["name"]
        approved = self.plant.part_requirements[eq_id]["approved_model"]
        seen = interp.get("model")
        if seen and norm_model(seen) == norm_model(approved):
            msg["data"]["seen"] = f"Same model as approved ({approved}). No action needed."
            await self.update_message(msg)
            return
        interp = {**interp, "tags": interp.get("tags") or self._tags_for_equipment(eq_id),
                  "summary": interp.get("summary") or f"{name} replaced without review"}
        await self.record_change(msg, interp, mode, kind="unreviewed")
        watchers = self.plant.risk_watchers()
        text = (f"🔍 Unreviewed change: {interp['summary']}. The {name} is a safeguard "
                f"({self.plant.part_requirements[eq_id]['safety_role'].split('.')[0].lower()}). "
                "Running the like-for-like check now.")
        await self.add_message(self._msg("sanjaya", "alert", text,
                                         speak=self._speak(watchers, f"Unreviewed change detected. {interp['summary']}.")))
        current, proposed = await self._read_specs(eq_id, [a for a in attachments if a["kind"] == "document"], seen)
        if not proposed:
            ask = "Please post the new part's nameplate photo or invoice so I can check it against the approved spec."
            await self.add_message(self._msg("sanjaya", "text", ask))
            return
        report = parts.evaluate(self.plant, eq_id, current, proposed, self.active_tags())
        report["unreviewed"] = True
        self._log("part_evaluated", proposed=report["proposed_model"], like_for_like=report["like_for_like"],
                  unreviewed=True, mode=mode)
        await self.add_message(self._msg("sanjaya", "report_card", report["verdict"], data={"report": report},
                                         speak=self._speak(watchers, parts.voice_summary(report, "Someone on the floor")
                                                           .replace("wants to switch", "has switched")
                                                           .replace(" What should I tell Someone on the floor?", ""))))

    # ---- demo helpers -------------------------------------------------------

    async def skip_wait(self, req_id):
        req = self.requests.get(req_id)
        if req and req["status"] == "pending":
            await self.escalate(req)
            await self.push_dashboard()

    async def close_change(self, change_id, user):
        for c in self.changes:
            if c["id"] == change_id and c["status"] == "active":
                c["status"] = "closed"
                self._log("change_closed", change=change_id, by=user)
                self._sync_levels()
                text = f"{self.plant.name(user)} restored: {c['summary']}."
                await self.add_message(self._msg("sanjaya", "text", f"✅ {text}"))
        await self.push_dashboard()
