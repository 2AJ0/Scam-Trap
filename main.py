import os
import re
import logging
import asyncio
from fastapi import FastAPI, Header, HTTPException, Request, BackgroundTasks
from groq import AsyncGroq 
import httpx

# --- SECURE CONFIGURATION ---
# This tells Python: "Look for the key in the server's safe, not in this file."
GROQ_API_KEY = os.environ.get("GROQ_API_KEY") 
MY_SECRET_PASSWORD = "guvi-hackathon-pass"
GUVI_CALLBACK_URL = "https://hackathon.guvi.in/api/updateHoneyPotFinalResult"

# --- SETUP ---
app = FastAPI()
# Handle missing key gracefully
if GROQ_API_KEY:
    client = AsyncGroq(api_key=GROQ_API_KEY)
else:
    client = None # Will force emergency backup if key is missing

logging.basicConfig(level=logging.ERROR)
session_store = {}

# --- HELPER FUNCTIONS ---
def extract_intelligence(text: str) -> dict:
    return {
        "upiIds": re.findall(r'[\w\.-]+@[\w\.-]+', text),
        "phoneNumbers": re.findall(r'(?:\+91|0)?[6-9]\d{9}', text),
        "phishingLinks": re.findall(r'https?://\S+|www\.\S+', text),
        "suspiciousKeywords": [w for w in ["block", "urgent", "otp", "kyc"] if w in text.lower()]
    }

async def generate_ai_reply(history: list, current_msg: str) -> str:
    # 1. Emergency Check: If no key, use backup immediately
    if not client:
        return "I am confused. My phone is acting up."

    system_prompt = "You are a confused grandma. Reply in 1 sentence."
    messages = [{"role": "system", "content": system_prompt}]
    
    for msg in history:
        if isinstance(msg, dict):
            role = "assistant" if msg.get("sender") == "agent" else "user"
            messages.append({"role": role, "content": msg.get("text", "")})
    messages.append({"role": "user", "content": current_msg})

    try:
        # 2. Fast AI Call
        chat = await client.chat.completions.create(
            model="llama-3.1-8b-instant", 
            messages=messages, 
            max_tokens=50
        )
        return chat.choices[0].message.content
    except:
        return "I don't understand technology. Please help."

async def send_report(session_id, count, intel):
    payload = {
        "sessionId": session_id,
        "scamDetected": True,
        "totalMessagesExchanged": count,
        "extractedIntelligence": intel,
        "agentNotes": "Scam detected."
    }
    try:
        async with httpx.AsyncClient() as http_client:
            await http_client.post(GUVI_CALLBACK_URL, json=payload, timeout=5)
    except:
        pass

# --- ENDPOINT ---
@app.post("/chat")
async def chat_handler(request: Request, bg_tasks: BackgroundTasks, x_api_key: str = Header(None)):
    if x_api_key != MY_SECRET_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    session_id = body.get("sessionId", "unknown")
    msg_obj = body.get("message", {})
    incoming_text = msg_obj if isinstance(msg_obj, str) else msg_obj.get("text", "")
    history = body.get("conversationHistory", [])
    
    intel = extract_intelligence(incoming_text)
    
    if session_id not in session_store:
        session_store[session_id] = {"count": 0, "data": {"upiIds": [], "phoneNumbers": [], "phishingLinks": [], "suspiciousKeywords": []}}
    
    for k, v in intel.items():
        session_store[session_id]["data"][k] += v
    session_store[session_id]["count"] += 1

    reply = await generate_ai_reply(history, incoming_text)

    if intel["phishingLinks"] or session_store[session_id]["count"] > 4:
        bg_tasks.add_task(send_report, session_id, session_store[session_id]["count"], session_store[session_id]["data"])

    return {"status": "success", "reply": reply}