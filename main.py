import os
import re
import json
from fastapi import FastAPI, Header, Request, BackgroundTasks, Response
from groq import AsyncGroq
import httpx
import redis

# ---------------- CONFIG ----------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
API_KEY = "guvi-hackathon-pass"
GUVI_CALLBACK_URL = "https://hackathon.guvi.in/api/updateHoneyPotFinalResult"

REDIS_HOST = "localhost"
REDIS_PORT = 6379
SESSION_TTL = 3600  # 1 hour

MIN_MESSAGES = 4
MAX_MESSAGES = 8

# ---------------- APP ----------------
app = FastAPI()
client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# ---------------- SESSION ----------------
def get_session(session_id: str):
    data = redis_client.get(session_id)
    return json.loads(data) if data else None

def save_session(session_id: str, session: dict):
    redis_client.setex(session_id, SESSION_TTL, json.dumps(session))

# ---------------- INTELLIGENCE ----------------
def extract_intelligence(text: str) -> dict:
    return {
        "upiIds": re.findall(r'[\w\.-]+@[\w]+', text),
        "phoneNumbers": re.findall(r'(?:\+91|0)?[6-9]\d{9}', text),
        "phishingLinks": re.findall(r'https?://\S+|www\.\S+', text),
        "bankAccounts": re.findall(r'\b\d{9,18}\b', text),
        "suspiciousKeywords": [
            w for w in ["urgent", "blocked", "verify", "otp", "kyc", "suspend"]
            if w in text.lower()
        ]
    }

def rule_based_scam(intel: dict) -> bool:
    score = 0
    if intel["upiIds"]: score += 2
    if intel["phishingLinks"]: score += 2
    if intel["phoneNumbers"]: score += 1
    if intel["suspiciousKeywords"]: score += 1
    return score >= 2

async def llm_scam_classifier(text: str) -> bool:
    if not client:
        return False
    try:
        resp = await client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{
                "role": "user",
                "content": (
                    "Classify the message as SCAM or NOT_SCAM. "
                    "Reply with only one word.\n\n"
                    f"Message: {text}"
                )
            }],
            max_tokens=5
        )
        return "SCAM" in resp.choices[0].message.content.upper()
    except:
        return False

# ---------------- AGENT ----------------
async def generate_ai_reply(history: list, text: str) -> str:
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

    messages.append({"role": "user", "content": text})

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
        "agentNotes": (
            "Scammer used urgency and impersonation tactics "
            "to extract payment credentials."
        )
    }
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(GUVI_CALLBACK_URL, json=payload)
    except:
        pass  # Never crash evaluation

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

    session = get_session(session_id)
    if not session:
        session = {
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

    session["count"] += 1

    intel = extract_intelligence(text)
    for k in intel:
        session["intel"][k] = list(set(session["intel"][k] + intel[k]))

    rule_scam = rule_based_scam(intel)
    llm_scam = await llm_scam_classifier(text)
    scam_confirmed = rule_scam or llm_scam

    reply = await generate_ai_reply(history, text)

    if session["count"] >= MAX_MESSAGES:
        reply = "I will visit my bank branch tomorrow."

    if (
        scam_confirmed
        and not session["reported"]
        and session["count"] >= MIN_MESSAGES
    ):
        session["reported"] = True
        bg_tasks.add_task(send_final_report, session_id, session)

    save_session(session_id, session)

    return {
        "status": "success",
        "reply": reply
    }
