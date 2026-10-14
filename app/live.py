"""Live voice call between an approver and Sanjaya over the Gemini Live API.

The phone streams 16 kHz PCM microphone audio over a WebSocket; this module relays it to a
Gemini Live session and streams Sanjaya's 24 kHz PCM voice back. Sanjaya's decisions still go
through the engine: the model calls `record_decision`, the engine produces the read-back text,
and only `confirm_decision` relays it. The model can't approve anything on its own.
"""
import asyncio
import json
import logging
import os

from fastapi import WebSocket, WebSocketDisconnect

from .engine import CURRENT_TRACE

log = logging.getLogger("sanjaya.live")
LIVE_MODEL = os.environ.get("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-09-2025")

try:
    from google.genai import types
except ImportError:  # pragma: no cover
    types = None

LANG_NAME = {"hi-IN": "Hindi (Hinglish is fine)", "te-IN": "Telugu", "en-IN": "English (Indian English)"}


def _tools():
    s = types.Schema
    return [types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="record_decision",
            description="Record the approver's decision once they have clearly said it. Returns the exact read-back "
                        "sentence you must say next.",
            parameters=s(type="OBJECT", properties={
                "decision": s(type="STRING", enum=["approve", "approve_with_conditions", "reject"]),
                "max_minutes": s(type="INTEGER", description="Time limit the approver set, if any"),
                "conditions": s(type="STRING", description="Other conditions the approver set, if any"),
            }, required=["decision"])),
        types.FunctionDeclaration(
            name="confirm_decision",
            description="Call after reading back, with whether the approver confirmed the read-back.",
            parameters=s(type="OBJECT", properties={"confirmed": s(type="BOOLEAN")}, required=["confirmed"])),
        types.FunctionDeclaration(
            name="search_documents",
            description="Search the plant's HAZOP, SOPs and standards. Use it to answer 'why' questions.",
            parameters=s(type="OBJECT", properties={"query": s(type="STRING")}, required=["query"])),
        types.FunctionDeclaration(
            name="get_risk_stacks",
            description="Live risk stack: each hazard and which safeguards are weakened right now."),
    ])]


def _system(engine, req, approver):
    user = engine.plant.user(approver)
    return f"""You are Sanjaya, the safety agent of {engine.plant.info['name']}. You are on a live voice call with
{user['name']} ({user['title']}). Speak {LANG_NAME.get(user['lang'], 'English')}, calmly, in short sentences.

Your job on this call: get a decision on this request and nothing else.
Request: {req['summary']} (asked by {engine.plant.name(req['requester'])}).
Your evaluation, based on the plant's documents: {req['evaluation']}

Rules:
1. Start by briefing the request in two or three sentences, then ask what to tell
   {engine.plant.name(req['requester'])}.
2. Answer questions only from the evaluation above or the tools, and name the document. Never invent a number.
3. When the decision is clear, call record_decision. Then say the read-back sentence it returns, word for word,
   and wait for the answer.
4. When they answer the read-back, call confirm_decision. If they correct you, ask for the decision again.
5. You never approve anything yourself. When the decision is confirmed, say you'll tell
   {engine.plant.name(req['requester'])} now, and say goodbye."""


async def run_call(ws: WebSocket, engine, approver, req_id):
    await ws.accept()
    req = engine.requests.get(req_id)
    if engine.brain.mode != "gemini" or not req:
        await ws.send_json({"type": "unavailable",
                            "reason": "Live voice needs Gemini (set GEMINI_API_KEY)." if req else "Unknown request"})
        await ws.close()
        return
    if approver not in req["approvers"] and approver != req.get("decider"):
        await ws.send_json({"type": "unavailable", "reason": "You're not an approver for this request."})
        await ws.close()
        return

    trace = await engine.begin_trace(f"Live call with {engine.plant.name(approver)}", req.get("msg_id"), approver)
    transcript = []
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(parts=[types.Part(text=_system(engine, req, approver))]),
        tools=_tools(),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )

    async def handle_tool(fc):
        args = dict(fc.args or {})
        if fc.name == "record_decision":
            await engine.step("gavel", "Heard the decision on the call", json.dumps(args), mode="gemini", trace=trace)
            await engine.decide(req, approver, {"decision": args.get("decision"),
                                                "max_minutes": args.get("max_minutes"),
                                                "conditions": args.get("conditions")}, via="live call")
            if req["status"] != "awaiting_readback":
                return {"error": "Could not record the decision. Ask again."}
            return {"read_back": req["readback_text"], "instruction": "Say this read-back word for word, then wait."}
        if fc.name == "confirm_decision":
            await engine.confirm(req, approver, bool(args.get("confirmed")), via="live call")
            return {"status": req["status"],
                    "relayed_to": engine.plant.name(req["requester"]) if req["status"] != "pending" else None}
        if fc.name in ("search_documents", "get_risk_stacks"):
            result = engine.tool_call(fc.name, args)
            cite = result[0].get("cite") if isinstance(result, list) and result and isinstance(result[0], dict) else None
            await engine.step("tool", "Looked something up during the call", json.dumps(args) if args else fc.name,
                              cite=cite, mode="gemini", trace=trace)
            return {"result": result}
        return {"error": "unknown tool"}

    try:
        async with engine.brain.gemini.client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            CURRENT_TRACE.set(trace)
            await ws.send_json({"type": "ready"})
            await engine.step("phone", "Started a live voice call", engine.plant.user(approver)["title"],
                              mode="gemini", trace=trace)
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text="(The approver has picked up. Brief them.)")]),
                turn_complete=True)

            async def upstream():
                while True:
                    msg = await ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        return
                    if msg.get("bytes"):
                        await session.send_realtime_input(
                            audio=types.Blob(data=msg["bytes"], mime_type="audio/pcm;rate=16000"))
                    elif msg.get("text") == "hangup":
                        return

            async def downstream():
                while True:
                    async for resp in session.receive():
                        if resp.data:
                            await ws.send_bytes(resp.data)
                        sc = resp.server_content
                        if sc:
                            if sc.input_transcription and sc.input_transcription.text:
                                transcript.append(("you", sc.input_transcription.text))
                                await ws.send_json({"type": "you", "text": sc.input_transcription.text})
                            if sc.output_transcription and sc.output_transcription.text:
                                transcript.append(("sanjaya", sc.output_transcription.text))
                                await ws.send_json({"type": "sanjaya", "text": sc.output_transcription.text})
                            if sc.interrupted:
                                await ws.send_json({"type": "interrupted"})
                        if resp.tool_call:
                            replies = []
                            for fc in resp.tool_call.function_calls:
                                result = await handle_tool(fc)
                                replies.append(types.FunctionResponse(id=fc.id, name=fc.name, response=result))
                                await ws.send_json({"type": "status", "request": engine._request_view(req)})
                            await session.send_tool_response(function_responses=replies)

            up = asyncio.create_task(upstream())
            down = asyncio.create_task(downstream())
            await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
            for t in (up, down):
                t.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.exception("Live call failed")
        try:
            await ws.send_json({"type": "error", "reason": str(exc)})
        except Exception:
            pass
    finally:
        text = _merge(transcript)
        engine._log("live_call", request=req_id, approver=approver, transcript=text)
        await engine.step("phone", "Call ended", f"{len(text)} turns logged with the request", trace=trace)
        engine.outcome(f"Live call: request is {req['status']}")
        await engine.end_trace()
        if text:
            await engine.add_message(engine._msg("sanjaya", "call_card",
                                                 f"Live call with {engine.plant.name(approver)}",
                                                 data={"request_id": req_id, "transcript": text,
                                                       "trace_id": trace["id"]}))
        await engine.push_dashboard()


def _merge(lines):
    """Join streaming transcription fragments into whole turns."""
    merged = []
    for who, text in lines:
        if merged and merged[-1]["who"] == who:
            merged[-1]["text"] += text
        else:
            merged.append({"who": who, "text": text})
    for m in merged:
        m["text"] = m["text"].strip()
    return [m for m in merged if m["text"]]
