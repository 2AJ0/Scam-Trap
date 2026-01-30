import os
import re
import logging
import json
from fastapi import FastAPI, Header, Request, BackgroundTasks, Response
from groq import AsyncGroq 
import httpx

# --- SECURE CONFIGURATION ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY") 
MY_SECRET_PASSWORD = "guvi-hackathon-pass"
GUVI_CALLBACK_URL = "https://hackathon.guvi.in/api/updateHoneyPotFinalResult"

# --- SETUP ---
app = FastAPI()

# Handle missing key gracefully (prevents startup crashes)
if GROQ_API_KEY:
    client = AsyncGroq(api_key=GROQ_API_KEY)
else:
    client = None 

# logging.basicConfig(level=logging.INFO) # maintain default logging
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
    # Emergency Backup if Key is missing or AI fails
    fallback_phrases = [
        "I am confused. My phone is acting up.",
        "I don't understand technology. Please help.",
        "Did you send this? I can't read it well.",
        "My grandson handles this usually."
    ]
    
    if not client:
        import random
        return random.choice(fallback_phrases)

    system_prompt = "You are a confused grandma. Reply in 1 sentence."
    messages = [{"role": "system", "content": system_prompt}]
    
    # Safe History Building
    for msg in history:
        if isinstance(msg, dict):
            role = "assistant" if msg.get("sender") == "agent" else "user"
            messages.append({"role": role, "content": msg.get("text", "")})
    messages.append({"role": "user", "content": current_msg})

    try:
        chat = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages, 
            max_tokens=50
        )
        return chat.choices[0].message.content
    except:
        import random
        return random.choice(fallback_phrases)

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

# --- THE UNCRASHABLE ENDPOINT ---
@app.post("/chat")
async def chat_handler(request: Request, bg_tasks: BackgroundTasks, x_api_key: str = Header(None)):
    # 1. AUTH CHECK (We keep this one)
    if x_api_key != MY_SECRET_PASSWORD:
        # Return 401 but log it
        print(f"❌ Wrong Password: {x_api_key}")
        return Response(content=json.dumps({"error": "Unauthorized"}), status_code=401, media_type="application/json")

    # 2. BULLETPROOF DATA READING (No more 400 Errors!)
    try:
        body = await request.json()
    except:
        # If JSON fails, assume empty body instead of crashing
        print("⚠️ Invalid JSON received, using empty body.")
        body = {}

    # 3. SAFE DATA EXTRACTION (Never fails)
    session_id = body.get("sessionId", "unknown_session")
    msg_obj = body.get("message", {})
    
    # Handle weird message formats
    if isinstance(msg_obj, str):
        incoming_text = msg_obj
    elif isinstance(msg_obj, dict):
        incoming_text = msg_obj.get("text", "")
    else:
        incoming_text = ""

    history = body.get("conversationHistory", [])
    
    # 4. PROCESS INTELLIGENCE
    intel = extract_intelligence(incoming_text)
    
    if session_id not in session_store:
        session_store[session_id] = {"count": 0, "data": {"upiIds": [], "phoneNumbers": [], "phishingLinks": [], "suspiciousKeywords": []}}
    
    for k, v in intel.items():
        session_store[session_id]["data"][k] += v
    session_store[session_id]["count"] += 1

    # 5. GENERATE REPLY
    reply = await generate_ai_reply(history, incoming_text)

    # 6. REPORT IN BACKGROUND
    if intel["phishingLinks"] or session_store[session_id]["count"] > 4:
        bg_tasks.add_task(send_report, session_id, session_store[session_id]["count"], session_store[session_id]["data"])

    # 7. ALWAYS RETURN SUCCESS
    return {"status": "success", "reply": reply}
