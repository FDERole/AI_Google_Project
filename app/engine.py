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
import contextvars
import itertools
import json
import logging
import re
import time

from . import fallback, onboarding, parts, risk
from .brain import Brain
from .docs import Library
from .config import DATA_DIR, ESCALATE_AFTER_MIN, REMIND_BEFORE_MIN, RUNTIME_DIR, DEMO_SPEED
from .plant import Plant

log = logging.getLogger("sanjaya.engine")

# Which weakened safeguard to suggest restoring first: quick, reversible fixes before slow ones.
RESTORE_PRIORITY = ["alarm", "nitrogen", "gas_detector", "fan", "hot_work", "batch_size", "crew_training"]

# The reasoning trace of the post currently being handled (one per asyncio task).
CURRENT_TRACE = contextvars.ContextVar("current_trace", default=None)

# Seconds of real time an approver gets before escalation, even when the demo clock is sped up.
MIN_ESCALATION_SECONDS = 45


KIND_LABEL = {
    "chat": "General chat, nothing to act on", "routine_change": "A change on the floor",
    "change_request": "A request that needs approval", "part_evaluation": "A request to evaluate a part",
    "unreviewed_part_change": "A part replaced without review", "started": "Change started",
    "finished": "Change finished",
}


TOOL_LABEL = {
    "get_risk_stacks": "Read the live risk stack", "get_active_changes": "Listed the active changes",
    "get_requests": "Checked open requests", "search_documents": "Searched the plant documents",
    "get_limit": "Looked up a documented limit",
}


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
        self.docs = Library()
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
        self.traces = []
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
        data = data or {}
        trace = CURRENT_TRACE.get()
        if author == "sanjaya" and trace and "trace_id" not in data:
            data["trace_id"] = trace["id"]
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
            "traces": list(reversed(self.traces))[:25],
        }

    # ---- reasoning trace ----------------------------------------------------
    # Every real step Sanjaya takes is streamed to the UI, with the document it relied on.

    async def begin_trace(self, title, msg_id=None, actor=None):
        trace = {"id": self._id("t"), "title": title, "msg_id": msg_id, "actor": actor,
                 "started_at": now_ms(), "steps": [], "status": "thinking", "outcome": None}
        self.traces.append(trace)
        self.traces = self.traces[-60:]
        CURRENT_TRACE.set(trace)
        await self.emit({"type": "trace", "trace": trace})
        return trace

    async def step(self, icon, label, detail="", cite=None, mode=None, level=None, trace=None):
        trace = trace or CURRENT_TRACE.get()
        if not trace:
            return
        trace["steps"].append({"icon": icon, "label": label, "detail": detail, "cite": cite, "mode": mode,
                               "level": level, "at": now_ms()})
        await self.emit({"type": "trace", "trace": trace})

    def outcome(self, text):
        trace = CURRENT_TRACE.get()
        if trace:
            trace["outcome"] = text

    async def end_trace(self, outcome=None):
        trace = CURRENT_TRACE.get()
        if not trace:
            return
        trace["status"] = "done"
        trace["outcome"] = outcome or trace["outcome"]
        trace["ms"] = now_ms() - trace["started_at"]
        await self.emit({"type": "trace", "trace": trace})
        CURRENT_TRACE.set(None)

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
        what = {"voice": "voice note", "photo": "photo", "file": "documents"}.get(mtype, "message")
        await self.begin_trace(f"{self.plant.name(author)}'s {what}", msg["id"], author)
        try:
            if transcript:
                await self.step("mic", "Listened to the voice note", f"“{transcript}”", mode=mode or "phone")
            await self.handle(msg, attachments)
        finally:
            await self.end_trace()
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
                await self.step("repeat", "Heard the answer to my read-back", f"{answer.upper()}", mode=_)
                await self.confirm(req, author, answer == "yes", via="voice" if voice else "text")
                return

        req = self._pending_for_approver(author, reply_to)
        if req:
            decision, mode = await asyncio.to_thread(self.brain.parse_decision, text, req["summary"], voice)
            if decision["decision"] != "unclear":
                said = decision["decision"].replace("_", " ") + (
                    f", max {decision['max_minutes']} min" if decision.get("max_minutes") else "")
                await self.step("gavel", f"Understood {self.plant.name(author)}'s decision on “{req['summary']}”",
                                said, mode=mode)
                await self.decide(req, author, decision, via="voice" if voice else "text")
                return

        req = self._requester_open_request(author)
        if req and req["status"] == "approved" and fallback.is_started(text):
            await self.step("play", "Recognised the start of an approved change", req["summary"])
            await self.start(req, author)
            return
        if req and req["status"] in ("active", "overrun") and fallback.is_finished(text):
            await self.step("check", "Recognised the change is finished", req["summary"])
            await self.finish(req, author)
            return

        if msg["type"] == "voice" and not text.strip():
            sorry = "I couldn't hear that voice note clearly. Please try again, type it, or use the buttons."
            await self.add_message(self._msg("sanjaya", "text", sorry, speak=self._speak([author], sorry)))
            return

        if self._is_question(text):
            await self.answer_question(msg, text)
            return

        interp, mode = await asyncio.to_thread(self.brain.interpret, text, author, attachments)
        kind = interp["kind"]
        if interp.get("seen"):
            await self.step("eye", "Looked at the photo", interp["seen"], mode=mode)
        await self.step("brain", "Understood the message", KIND_LABEL.get(kind, kind) +
                        (f": {interp['summary']}" if interp.get("summary") else ""), mode=mode)
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
        if kind == "chat":
            self.outcome("No safety-relevant change")

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
        for tag in change["tags"]:
            policy = self.plant.data.get("tag_policies", {}).get(tag)
            if policy:
                await self.step("book", "Checked the plant's rules", policy["rule"], cite=self.docs.cite(policy))
        await self.step("pen", "Logged the change", change["summary"])
        await self.check_stacks()
        return change

    async def check_stacks(self):
        stacks = risk.evaluate(self.plant, self.active_changes())
        hot = [s for s in stacks if s["degraded"]]
        if CURRENT_TRACE.get():
            summary = "; ".join(f"{s['hazard']}: {len(s['degraded'])}/{s['total_barriers']} weakened "
                                f"({s['level']['name']})" for s in hot) or "All safeguards in place"
            worst = max((s["level"]["rank"] for s in stacks), default=0)
            await self.step("layers", "Re-judged every hazard against all active changes together", summary,
                            level=risk.level_for(worst)["name"])
        for stack in sorted(stacks, key=lambda x: -x["level"]["rank"]):
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
        await self.step("bell", f"Alerted {self._names(watchers)} by voice",
                        f"{stack['hazard']} is {stack['level']['name']}", level=stack["level"]["name"])
        await self.add_message(msg)
        trace = CURRENT_TRACE.get()
        if trace and not trace["outcome"]:  # keep the worst alert (stacks are checked worst-first)
            self.outcome(f"{stack['hazard']}: {stack['level']['name']}")

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

        if limit:
            await self.step("book", f"Looked up the documented limit for {eq['name']}",
                            f"Max {limit['max_minutes']} min {limit['condition']}: {limit['consequence_en']}",
                            cite=self.docs.cite(limit.get("doc")))
        else:
            await self.step("alert", f"Searched the plant documents for a safe {action} limit",
                            "None documented. I will say so instead of guessing.", level="watch")
        lines = [f"{self.plant.name(requester)} has asked to {action.replace('shutdown', 'shut down')} "
                 f"{eq['name']} in {self.plant.info['name']}."]
        if limit:
            lines.append(f"If it's off for more than {limit['max_minutes']} minutes {limit['condition']}, "
                         f"{limit['consequence_en']} ({self.docs.cite(limit.get('doc')) or limit['source']}), "
                         "so it must be monitored.")
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
        await self.step("layers", "Checked what else is active on the same hazards",
                        " ".join(stack_lines) or "No other weakened safeguards on these hazards",
                        level="critical" if any("3 of" in x or "4 of" in x for x in stack_lines) else
                        ("elevated" if stack_lines else None))
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
        approver_desc = ", ".join(f"{self.plant.name(a)} ({self.plant.user(a)['title']})" for a in req["approvers"])
        await self.step("route", "Routed to the person with authority", f"{approver_desc}, level 1. "
                        f"Escalates after {ESCALATE_AFTER_MIN:g} min without a reply.")
        await self.step("speaker", f"Spoke the evaluation to {self._names(req['approvers'])}", "")
        self.outcome(f"Sent to {self._names(req['approvers'])} for a decision")
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
        view["limit_cite"] = self.docs.cite(req["limit"].get("doc")) if req.get("limit") else None
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
        await self.step("repeat", "Read the decision back before relaying it", warning + readback,
                        level="elevated" if warning else None)
        self.outcome("Waiting for read-back confirmation")
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
        await self.step("send", f"Relayed the confirmed decision to {self.plant.name(req['requester'])}",
                        f"in {'Hindi' if self.plant.user(req['requester'])['lang'] == 'hi-IN' else 'English'}")
        self.outcome(("Approved" if approved else "Rejected") + f" by {self.plant.name(user)}")
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
                found = ", ".join(f"{k.replace('_m3h', '').replace('_inr', '').replace('_', ' ')}: {v}"
                                  for k, v in specs.items() if k != "model" and v)
                await self.step("file", f"Read {att.get('name') or 'the attachment'}",
                                f"{specs.get('model') or 'Unknown model'}. {found or 'No specs found'}", mode=mode)
        current = next((s for s in extracted if s.get("model") and
                        norm_model(approved).endswith(norm_model(s["model"].split()[-1]))), None)
        proposed = next((s for s in extracted if s is not current and s.get("model")), None)
        if current is None:
            current = await asyncio.to_thread(self._library_specs, approved) or {"model": approved}
            await self.step("folder", "Pulled the approved part's datasheet from the plant library", approved)
        if (proposed is None or not any(v for k, v in proposed.items() if k != "model")) and seen_model:
            proposed = await asyncio.to_thread(self._library_specs, seen_model) or proposed
        return current, proposed

    async def _compare_with_steps(self, eq_id, current, proposed):
        spec = self.plant.part_requirements[eq_id]
        hz = self.plant.hazard(spec["hazard"])
        await self.step("shield", f"Found what the {self.plant.equipment[eq_id]['name']} does for safety",
                        spec["safety_role"], cite=self.docs.cite(hz.get("doc")))
        report = parts.evaluate(self.plant, eq_id, current, proposed, self.active_tags())
        bad = [f"{r['label']}: {r['note']}" for r in report["rows"] if r["status"] in ("fail", "missing")]
        await self.step("scale", "Compared only the safety-critical specs",
                        "; ".join(bad) or "Every safety-critical spec matches",
                        cite=self.docs.cite(spec.get("doc")), level="critical" if bad else None)
        for note in report["plant_state"]:
            await self.step("layers", "Checked the plant's current state", note, level="elevated")
        self.outcome("Like-for-like" if report["like_for_like"] else "Not like-for-like: recommend rejecting")
        return report

    async def evaluate_part(self, msg, interp, attachments, mode):
        eq_id = interp.get("equipment") if interp.get("equipment") in self.plant.part_requirements else "EF-04"
        asker = msg["author"]
        current, proposed = await self._read_specs(eq_id, attachments, interp.get("model"))
        if not proposed:
            text = ("Please attach the new supplier's datasheet (and the current one if you have it). "
                    "I won't evaluate a part from its name alone.")
            await self.add_message(self._msg("sanjaya", "text", text, speak=self._speak([asker], text)))
            return
        report = await self._compare_with_steps(eq_id, current, proposed)
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
        report = await self._compare_with_steps(eq_id, current, proposed)
        report["unreviewed"] = True
        self._log("part_evaluated", proposed=report["proposed_model"], like_for_like=report["like_for_like"],
                  unreviewed=True, mode=mode)
        await self.add_message(self._msg("sanjaya", "report_card", report["verdict"], data={"report": report},
                                         speak=self._speak(watchers, parts.voice_summary(report, "Someone on the floor")
                                                           .replace("wants to switch", "has switched")
                                                           .replace(" What should I tell Someone on the floor?", ""))))

    # ---- ASK: questions to Sanjaya -----------------------------------------

    @staticmethod
    def _is_question(text):
        return bool(re.match(r"\s*(@?sanjaya|संजय)\b[\s,:!-]*\S", text or "", re.IGNORECASE))

    def tool_call(self, name, args):
        """Read-only tools the question-answering agent can call. Never changes plant state."""
        if name == "get_risk_stacks":
            return [{"hazard": s["hazard"], "level": s["level"]["name"],
                     "weakened": [d["barrier"] for d in s["degraded"]],
                     "total_safeguards": s["total_barriers"], "source": self.docs.cite(
                         self.plant.hazard(s["hazard_id"]).get("doc"))}
                    for s in risk.evaluate(self.plant, self.active_changes())]
        if name == "get_active_changes":
            return [{"summary": c["summary"], "by": c["by_name"], "kind": c["kind"]} for c in self.active_changes()]
        if name == "get_requests":
            return [{"summary": r["summary"], "status": r["status"], "requester": self.plant.name(r["requester"]),
                     "decided_by": self.plant.name(r["decider"]) if r.get("decider") else None,
                     "max_minutes": r.get("max_minutes")} for r in self.requests.values()]
        if name == "search_documents":
            return [{"cite": self.docs.cite(h), "heading": h["heading"], "text": h["text"]}
                    for h in self.docs.search(args.get("query", ""), 3)]
        if name == "get_limit":
            lim = self.plant.find_limit(args.get("equipment_id"), args.get("action"))
            return {**lim, "cite": self.docs.cite(lim.get("doc"))} if lim else {"found": False}
        return {"error": f"unknown tool {name}"}

    async def answer_question(self, msg, text):
        asker = msg["author"]
        question = re.sub(r"^\s*(@?sanjaya|संजय)\b[\s,:!-]*", "", text, flags=re.IGNORECASE)
        trace = CURRENT_TRACE.get()
        loop = asyncio.get_running_loop()

        def on_tool(name, args, result):
            label = TOOL_LABEL.get(name, name)
            detail = json.dumps(args, ensure_ascii=False) if args else ""
            cite = None
            if isinstance(result, list) and result and isinstance(result[0], dict) and result[0].get("cite"):
                cite = result[0]["cite"]
            elif isinstance(result, dict) and result.get("cite"):
                cite = result["cite"]
            asyncio.run_coroutine_threadsafe(
                self.step("tool", label, detail, cite=cite, mode="gemini", trace=trace), loop)

        answer, mode = await asyncio.to_thread(self.brain.ask, question, self.plant.user(asker), self.tool_call,
                                               on_tool)
        if not answer:
            answer = await self._offline_answer(question)
            mode = "offline"
        await self.step("speaker", f"Answered {self.plant.name(asker)}", "", mode=mode)
        self.outcome("Answered a question")
        await self.add_message(self._msg("sanjaya", "text", answer, data={"reply_to": msg["id"], "answer": True},
                                         speak=self._speak([asker], answer), mode=mode))

    async def _offline_answer(self, question):
        parts_ = []
        if re.search(r"risk|danger|status|safe|kya chal|halat|riskiest|stack", question, re.IGNORECASE):
            stacks = self.tool_call("get_risk_stacks", {})
            await self.step("layers", "Read the live risk stack",
                            "; ".join(f"{s['hazard']}: {s['level']}" for s in stacks))
            hot = sorted([s for s in stacks if s["weakened"]], key=lambda s: -len(s["weakened"]))
            if hot:
                top = hot[0]
                parts_.append(f"The biggest risk right now is {_lc(top['hazard'])}: "
                              f"{len(top['weakened'])} of {top['total_safeguards']} safeguards are weakened "
                              f"({', '.join(top['weakened'])}).")
            else:
                parts_.append("All safeguards are in place right now.")
        hits = self.tool_call("search_documents", {"query": question})
        if hits:
            await self.step("book", "Searched the plant documents", hits[0]["heading"], cite=hits[0]["cite"])
            if not parts_:
                hit = hits[0]
                body = hit["text"].replace(hit["heading"], "").strip()
                parts_.append(f"{hit['cite']} says: {body[:260].rsplit(' ', 1)[0]}…" if len(body) > 260 else
                              f"{hit['cite']} says: {body}")
        if not parts_:
            parts_.append("I couldn't find that in the plant's documents, so I won't guess.")
        return " ".join(parts_)

    # ---- TEACH: draft the risk model from the plant's documents ------------

    async def onboard(self, attachments, actor):
        await self.begin_trace("Teaching Sanjaya the plant", actor=actor)
        try:
            for att in attachments:
                pages = await asyncio.to_thread(onboarding.pages_of, att)
                await self.step("file", f"Reading {att['name']}", f"{pages} page{'s' if pages > 1 else ''}",
                                mode=self.brain.mode)
            draft, mode = None, "offline"
            if self.brain.mode == "gemini":
                known = {b["tag"] for h in self.plant.hazards for b in h["barriers"]}
                try:
                    draft = await asyncio.to_thread(onboarding.extract_with_gemini, self.brain.gemini.client,
                                                    attachments, known)
                    mode = "gemini"
                except Exception as exc:
                    log.warning("Onboarding extraction failed, using pre-computed draft: %s", exc)
            if draft is None:
                draft = onboarding.draft_from_current_model(self.plant, self.docs)
            for hz in draft["hazards"]:
                src = hz["source"]
                await self.step("shield", f"Hazard: {hz['name']}",
                                f"{len(hz['barriers'])} safeguards: " + ", ".join(b["name"] for b in hz["barriers"]),
                                cite=f"{src['doc']} {src['section']}" + (f", p.{src['page']}" if src.get("page") else ""),
                                mode=mode)
            for lim in draft["limits"]:
                src = lim["source"]
                await self.step("book", f"Limit: {lim['equipment']} {lim['action']}",
                                f"{lim['value']:g} {lim['unit']}" + (f" {lim['condition']}" if lim.get("condition") else ""),
                                cite=f"{src['doc']} {src['section']}" + (f", p.{src['page']}" if src.get("page") else ""),
                                mode=mode)
            for gap in draft["gaps"]:
                await self.step("alert", "Gap for the safety officer to check", gap, level="watch", mode=mode)
            draft["mode"] = mode
            draft["documents"] = [a["name"] for a in attachments]
            self.pending_draft = draft
            self.outcome(f"Draft ready: {len(draft['hazards'])} hazards, "
                         f"{sum(len(h['barriers']) for h in draft['hazards'])} safeguards, "
                         f"{len(draft['limits'])} limits. Waiting for safety-officer approval.")
            self._log("risk_model_drafted", documents=draft["documents"], mode=mode,
                      hazards=len(draft["hazards"]), limits=len(draft["limits"]))
            return draft
        finally:
            await self.end_trace()
            await self.push_dashboard()

    async def approve_model(self, actor):
        draft = getattr(self, "pending_draft", None)
        if not draft:
            return False
        if draft["mode"] == "gemini":
            hazards = []
            for i, hz in enumerate(draft["hazards"], start=1):
                hazards.append({
                    "id": f"H{i}", "name": hz["name"], "area": hz["area"],
                    "source": f"{hz['source']['doc']} {hz['source']['section']}",
                    "doc": {"doc": hz["source"]["doc"], "section": hz["source"]["section"]},
                    "barriers": [{"id": f"B{i}-{j}", "name": b["name"], "tag": b["tag"]}
                                 for j, b in enumerate(hz["barriers"], start=1)],
                })
            self.plant.hazards = hazards
            self.last_levels = {h["id"]: 0 for h in hazards}
            self._sync_levels()
        n_barriers = sum(len(h["barriers"]) for h in draft["hazards"])
        self._log("risk_model_approved", by=actor, hazards=len(draft["hazards"]), safeguards=n_barriers)
        text = (f"✅ {self.plant.name(actor)} approved the risk model drafted from {len(draft['documents'])} documents: "
                f"{len(draft['hazards'])} hazards, {n_barriers} safeguards and {len(draft['limits'])} limits, "
                "each cited to its page. I'll judge every change against it.")
        await self.add_message(self._msg("sanjaya", "text", text))
        self.pending_draft = None
        await self.push_dashboard()
        return True

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
