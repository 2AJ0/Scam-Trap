import os
import re
import json
from fastapi import FastAPI, Header, Request, BackgroundTasks, Response
from groq import AsyncGroq
import httpx

# ---------------- CONFIG ----------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
API_KEY = "guvi-hackathon-pass"
GUVI_CALLBACK_URL = "https://hackathon.guvi.in/api/updateHoneyPotFinalResult"

app = FastAPI()
client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# In-memory session store (OK for hackathon)
session_store = {}

# ---------------- INTELLIGENCE ----------------
def extract_intelligence(text: str) -> dict:
    return {
        "upiIds": re.findall(r'[\w\.-]+@[\w]+', text),
        "phoneNumbers": re.findall(r'(?:\+91|0)?[6-9]\d{9}', text),
        "phishingLinks": re.findall(r'https?://\S+|www\.\S+', text),
        "bankAccounts": re.findall(r'\b\d{9,18}\b', text),
        "suspiciousKeywords": [
            w for w in ["urgent", "blocked", "verify", "otp", "kyc"]
            if w in text.lower()
        ]
    }

def is_scam(intel: dict, text: str) -> bool:
    score = 0
    if intel["upiIds"]: score += 2
    if intel["phishingLinks"]: score += 2
    if intel["phoneNumbers"]: score += 1
    if intel["suspiciousKeywords"]: score += 1
    return score >= 2

# ---------------- AGENT ----------------
async def generate_ai_reply(history: list, current_msg: str) -> str:
    if not client:
        return "I am not very good with phones, can you explain slowly?"

    system_prompt = (
        "You are a confused non-technical user. "
        "Reply with exactly ONE short sentence. "
        "Ask for clarification politely."
    )

    messages = [{"role": "system", "content": system_prompt}]

    for msg in history[-3:]:
        sender = msg.get("sender")
        role = "assistant" if sender == "user" else "user"
        messages.append({"role": role, "content": msg.get("text", "")})

    messages.append({"role": "user", "content": current_msg})

    try:
        resp = await client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=30
        )
        return resp.choices[0].message.content.strip()
    except:
        return "Sorry, can you repeat that once?"

# ---------------- CALLBACK ----------------
async def send_final_report(session_id: str, session: dict):
    payload = {
        "sessionId": session_id,
        "scamDetected": True,
        "totalMessagesExchanged": session["count"],
        "extractedIntelligence": session["intel"],
        "agentNotes": "Scammer used urgency and attempted credential extraction"
    }
    async with httpx.AsyncClient() as client:
        await client.post(GUVI_CALLBACK_URL, json=payload, timeout=5)

# ---------------- API ----------------
@app.post("/chat")
async def chat_handler(
    request: Request,
    bg_tasks: BackgroundTasks,
    x_api_key: str = Header(None)
):
    if x_api_key != API_KEY:
        return Response(
            content=json.dumps({"status": "error", "message": "Unauthorized"}),
            status_code=401
        )

    body = await request.json()
    session_id = body.get("sessionId")
    message = body.get("message", {})
    text = message.get("text", "")
    history = body.get("conversationHistory", [])

    if session_id not in session_store:
        session_store[session_id] = {
            "count": 0,
            "reported": False,
            "intel": {
                "upiIds": [],
                "phoneNumbers": [],
                "phishingLinks": [],
                "bankAccounts": [],
                "suspiciousKeywords": []
            }
        }

    session = session_store[session_id]
    session["count"] += 1

    intel = extract_intelligence(text)
    for k in intel:
        session["intel"][k] = list(set(session["intel"][k] + intel[k]))

    scam_confirmed = is_scam(intel, text)

    reply = await generate_ai_reply(history, text)

    # Stop engagement after enough messages
    if session["count"] >= 8:
        reply = "I will visit my bank directly tomorrow."

    # Final mandatory callback (ONLY ONCE)
    if scam_confirmed and not session["reported"] and session["count"] >= 4:
        session["reported"] = True
        bg_tasks.add_task(send_final_report, session_id, session)

    return {
        "status": "success",
        "reply": reply
    }
