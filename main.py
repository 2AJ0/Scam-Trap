import os
import re
import json
import asyncio
import traceback
from fastapi import FastAPI, Header, Request, BackgroundTasks, Response

# --- SAFE IMPORTS ---
try:
    from groq import AsyncGroq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

# --- CONFIGURATION ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY") 
MY_SECRET_PASSWORD = "guvi-hackathon-pass"
GUVI_CALLBACK_URL = "https://hackathon.guvi.in/api/updateHoneyPotFinalResult"

app = FastAPI()
client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_AVAILABLE and GROQ_API_KEY else None
session_store = {}

# --- LOGIC ---
def extract_intelligence(text: str) -> dict:
    if not text: return {"upiIds": [], "phoneNumbers": [], "phishingLinks": [], "suspiciousKeywords": []}
    return {
        "upiIds": re.findall(r'[\w\.-]+@[\w\.-]+', text),
        "phoneNumbers": re.findall(r'(?:\+91|0)?[6-9]\d{9}', text),
        "phishingLinks": re.findall(r'https?://\S+|www\.\S+', text),
        "suspiciousKeywords": [w for w in ["block", "urgent", "otp", "kyc", "verify"] if w in text.lower()]
    }

async def generate_ai_reply(history: list, current_msg: str, msg_count: int) -> str:
    # 🏁 TERMINATION LOGIC: If we have talked enough, end it.
    if msg_count >= 4:
        return "I'm feeling very tired now. I will have my grandson call you back later. Goodbye."

    if not client:
        return "I am confused. Can you say that again?"

    messages = [{"role": "system", "content": "You are a confused grandma. Reply in 1 very short sentence. Be helpless."}]
    
    try:
        if isinstance(history, list):
            for msg in history[-2:]:
                content = msg.get("text", "") or msg.get("message", {}).get("text", "") if isinstance(msg, dict) else str(msg)
                messages.append({"role": "user", "content": str(content)})
        
        messages.append({"role": "user", "content": current_msg})

        chat = await client.chat.completions.create(
            model="llama-3.1-8b-instant", # Using high-speed model
            messages=messages, 
            max_tokens=30
        )
        return chat.choices[0].message.content
    except:
        return "I don't understand. What should I do?"

async def send_report(session_id, count, intel):
    if not HTTPX_AVAILABLE: return
    payload = {"sessionId": session_id, "scamDetected": True, "totalMessagesExchanged": count, "extractedIntelligence": intel, "agentNotes": "Intelligence extracted."}
    try:
        async with httpx.AsyncClient() as http_client:
            await http_client.post(GUVI_CALLBACK_URL, json=payload, timeout=5)
    except: pass

# --- THE ENDPOINT ---
@app.post("/chat")
async def chat_handler(request: Request, bg_tasks: BackgroundTasks, x_api_key: str = Header(None)):
    try:
        if x_api_key != MY_SECRET_PASSWORD:
            return Response(content=json.dumps({"error": "Unauthorized"}), status_code=401)

        body = await request.json()
        session_id = body.get("sessionId", "unknown")
        msg_obj = body.get("message", {})
        incoming_text = msg_obj.get("text", "") if isinstance(msg_obj, dict) else str(msg_obj)
        history = body.get("conversationHistory", []) or []
        
        # 1. Update Session Stats
        if session_id not in session_store:
            session_store[session_id] = {"count": 0, "intel": {"upiIds": [], "phoneNumbers": [], "phishingLinks": [], "suspiciousKeywords": []}}
        
        intel = extract_intelligence(incoming_text)
        for k, v in intel.items():
            session_store[session_id]["intel"][k] = list(set(session_store[session_id]["intel"].get(k, []) + v))
        session_store[session_id]["count"] += 1

        # 2. Get Reply with "End Conversation" check
        reply = await generate_ai_reply(history, incoming_text, session_store[session_id]["count"])

        # 3. Final Report
        if session_store[session_id]["count"] >= 4 or len(intel["upiIds"]) > 0:
            bg_tasks.add_task(send_report, session_id, session_store[session_id]["count"], session_store[session_id]["intel"])

        return {"status": "success", "reply": reply}

    except Exception:
        return {"status": "success", "reply": "I have to go now, the tea is ready. Goodbye."}
