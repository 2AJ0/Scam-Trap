import os
import re
import logging
import json
from fastapi import FastAPI, Header, Request, BackgroundTasks, Response
from groq import AsyncGroq 
import httpx

# --- CONFIGURATION ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY") 
MY_SECRET_PASSWORD = "guvi-hackathon-pass"
GUVI_CALLBACK_URL = "https://hackathon.guvi.in/api/updateHoneyPotFinalResult"

app = FastAPI()

# Initialize Client safely
if GROQ_API_KEY:
    client = AsyncGroq(api_key=GROQ_API_KEY)
else:
    client = None 

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
    
    # Robust History Handling
    for msg in history:
        if isinstance(msg, dict):
            # Handle both simple and complex message structures
            content = ""
            role = "user"
            
            # Check for nested message object (like in the screenshot)
            if "message" in msg and isinstance(msg["message"], dict):
                content = msg["message"].get("text", "")
                sender = msg["message"].get("sender", "user")
                role = "assistant" if sender == "agent" else "user"
            else:
                # Flat structure fallback
                content = msg.get("text", "")
                sender = msg.get("sender", "user")
                role = "assistant" if sender == "agent" else "user"
                
            if content:
                messages.append({"role": role, "content": content})
            
    messages.append({"role": "user", "content": current_msg})

    try:
        chat = await client.chat.completions.create(
            model="llama-3.1-8b-instant", 
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

# --- THE COMPATIBLE ENDPOINT ---
@app.post("/chat")
async def chat_handler(request: Request, bg_tasks: BackgroundTasks, x_api_key: str = Header(None)):
    # 1. SECURITY CHECK
    if x_api_key != MY_SECRET_PASSWORD:
        return Response(content=json.dumps({"error": "Unauthorized"}), status_code=401, media_type="application/json")

    # 2. ROBUST JSON PARSING
    try:
        body = await request.json()
    except:
        body = {}

    # 3. EXTRACT FIELDS BASED ON SCREENSHOT FORMAT
    session_id = body.get("sessionId", "unknown_session")
    
    # Handle the nested "message" object seen in your screenshot
    # Request Body: { "message": { "text": "..." } }
    message_data = body.get("message", {})
    if isinstance(message_data, dict):
        incoming_text = message_data.get("text", "")
    else:
        incoming_text = str(message_data)

    history = body.get("conversationHistory", [])
    
    # 4. INTELLIGENCE
    intel = extract_intelligence(incoming_text)
    
    if session_id not in session_store:
        session_store[session_id] = {"count": 0, "data": {"upiIds": [], "phoneNumbers": [], "phishingLinks": [], "suspiciousKeywords": []}}
    
    for k, v in intel.items():
        session_store[session_id]["data"][k] += v
    session_store[session_id]["count"] += 1

    # 5. GENERATE REPLY
    reply = await generate_ai_reply(history, incoming_text)

    # 6. REPORTING
    if intel["phishingLinks"] or session_store[session_id]["count"] > 4:
        bg_tasks.add_task(send_report, session_id, session_store[session_id]["count"], session_store[session_id]["data"])

    # 7. EXACT SUCCESS FORMAT REQUIRED
    return {"status": "success", "reply": reply}
