import os
import re
import json
import random
from fastapi import FastAPI, Header, Request, BackgroundTasks, Response
from groq import AsyncGroq 
import httpx

# --- CONFIGURATION ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY") 
MY_SECRET_PASSWORD = "guvi-hackathon-pass"
GUVI_CALLBACK_URL = "https://hackathon.guvi.in/api/updateHoneyPotFinalResult"

app = FastAPI()
client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
session_store = {}

# --- INTELLIGENCE EXTRACTION ---
def extract_intelligence(text: str) -> dict:
    return {
        "upiIds": re.findall(r'[\w\.-]+@[\w\.-]+', text),
        "phoneNumbers": re.findall(r'(?:\+91|0)?[6-9]\d{9}', text),
        "phishingLinks": re.findall(r'https?://\S+|www\.\S+', text),
        "suspiciousKeywords": [w for w in ["block", "urgent", "otp", "kyc", "verify"] if w in text.lower()]
    }

# --- AI BRAIN ---
async def generate_ai_reply(history: list, current_msg: str) -> str:
    if not client:
        return "I am so confused with this phone. Can you help me slowly?"

    # Short, personality-driven prompt to prevent long loops
    system_prompt = "You are a confused grandma. Keep your reply to exactly ONE short sentence. Be helpless."
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add history safely
    for msg in history[-3:]: # Only look at last 3 messages for speed
        if isinstance(msg, dict):
            m = msg.get("message", msg)
            content = m.get("text", "") if isinstance(m, dict) else str(m)
            sender = m.get("sender", "user") if isinstance(m, dict) else "user"
            messages.append({"role": "assistant" if sender == "agent" else "user", "content": content})
            
    messages.append({"role": "user", "content": current_msg})

    try:
        chat = await client.chat.completions.create(
            model="llama-3.1-8b-instant", # High-speed model
            messages=messages, 
            max_tokens=40
        )
        return chat.choices[0].message.content
    except:
        return "Oh dear, the screen went blank. What was that again?"

# --- REPORTING ---
async def send_report(session_id, count, intel):
    payload = {
        "sessionId": session_id,
        "scamDetected": True,
        "totalMessagesExchanged": count,
        "extractedIntelligence": intel,
        "agentNotes": "Scammer engagement successful. Intelligence extracted."
    }
    try:
        async with httpx.AsyncClient() as http_client:
            await http_client.post(GUVI_CALLBACK_URL, json=payload, timeout=5)
    except:
        pass

# --- THE ENDPOINT ---
@app.post("/chat")
async def chat_handler(request: Request, bg_tasks: BackgroundTasks, x_api_key: str = Header(None)):
    if x_api_key != MY_SECRET_PASSWORD:
        return Response(content=json.dumps({"status": "error", "message": "Unauthorized"}), status_code=401)

    try:
        body = await request.json()
    except:
        body = {}

    session_id = body.get("sessionId", "temp_session")
    msg_data = body.get("message", {})
    incoming_text = msg_data.get("text", "") if isinstance(msg_data, dict) else str(msg_data)
    
    # Process Stats
    intel = extract_intelligence(incoming_text)
    if session_id not in session_store:
        session_store[session_id] = {"count": 0, "intel": {"upiIds": [], "phoneNumbers": [], "phishingLinks": [], "suspiciousKeywords": []}}
    
    for k, v in intel.items():
        session_store[session_id]["intel"][k] = list(set(session_store[session_id]["intel"][k] + v))
    session_store[session_id]["count"] += 1

    # Generate AI Reply
    reply = await generate_ai_reply(body.get("conversationHistory", []), incoming_text)

    # Trigger reporting if scam confirmed or conversation is long enough
    if len(intel["upiIds"]) > 0 or session_store[session_id]["count"] >= 3:
        bg_tasks.add_task(send_report, session_id, session_store[session_id]["count"], session_store[session_id]["intel"])

    # FINAL RESPONSE FORMAT (Matches GUVI Expectation)
    return {"status": "success", "reply": reply}
