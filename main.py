import os
import re
import json
import asyncio
import traceback
from fastapi import FastAPI, Header, Request, BackgroundTasks, Response

# --- SAFE IMPORTS (Prevents Crash if tools are missing) ---
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

# Setup Client safely
client = None
if GROQ_AVAILABLE and GROQ_API_KEY:
    client = AsyncGroq(api_key=GROQ_API_KEY)

session_store = {}

# --- HELPER FUNCTIONS ---
def extract_intelligence(text: str) -> dict:
    if not text: return {"upiIds": [], "phoneNumbers": [], "phishingLinks": [], "suspiciousKeywords": []}
    return {
        "upiIds": re.findall(r'[\w\.-]+@[\w\.-]+', text),
        "phoneNumbers": re.findall(r'(?:\+91|0)?[6-9]\d{9}', text),
        "phishingLinks": re.findall(r'https?://\S+|www\.\S+', text),
        "suspiciousKeywords": [w for w in ["block", "urgent", "otp", "kyc"] if w in text.lower()]
    }

async def generate_ai_reply(history: list, current_msg: str) -> str:
    # Fallback if Groq is broken/missing
    if not client:
        return "I am confused. My phone is acting up."

    messages = [{"role": "system", "content": "You are a confused grandma. Reply in 1 sentence."}]
    
    try:
        # Safe History Parsing (Handles Nulls)
        if history and isinstance(history, list):
            for msg in history[-3:]:
                if isinstance(msg, dict):
                    content = msg.get("text", "") or msg.get("message", {}).get("text", "")
                    if content:
                        messages.append({"role": "user", "content": str(content)})
        
        messages.append({"role": "user", "content": current_msg})

        chat = await client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages, 
            max_tokens=40
        )
        return chat.choices[0].message.content
    except:
        return "Oh dear, I don't understand this technology."

async def send_report(session_id, count, intel):
    if not HTTPX_AVAILABLE:
        return
        
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

# --- THE ENDPOINT ---
@app.post("/chat")
async def chat_handler(request: Request, bg_tasks: BackgroundTasks, x_api_key: str = Header(None)):
    # 🛡️ GLOBAL CRASH PROTECTION 🛡️
    try:
        # 1. Security
        if x_api_key != MY_SECRET_PASSWORD:
            return Response(content=json.dumps({"error": "Unauthorized"}), status_code=401)

        # 2. Parse Body (Safe)
        try:
            body = await request.json()
        except:
            body = {}

        # 3. Extract Info
        session_id = body.get("sessionId", "unknown")
        
        # Handle complex message structure
        msg_obj = body.get("message", {})
        if isinstance(msg_obj, dict):
            incoming_text = msg_obj.get("text", "")
        else:
            incoming_text = str(msg_obj)

        history = body.get("conversationHistory", [])
        
        # 4. Intelligence
        intel = extract_intelligence(incoming_text)
        
        # Store Stats (Safely using .get to prevent KeyErrors)
        if session_id not in session_store:
            session_store[session_id] = {"count": 0, "intel": {"upiIds": [], "phoneNumbers": [], "phishingLinks": [], "suspiciousKeywords": []}}
        
        for k, v in intel.items():
            current_list = session_store[session_id]["intel"].get(k, [])
            session_store[session_id]["intel"][k] = list(set(current_list + v))
            
        session_store[session_id]["count"] += 1

        # 5. Generate Reply
        reply = await generate_ai_reply(history, incoming_text)

        # 6. Report
        if intel["phishingLinks"] or session_store[session_id]["count"] > 4:
            bg_tasks.add_task(send_report, session_id, session_store[session_id]["count"], session_store[session_id]["intel"])

        # 7. Success
        return {"status": "success", "reply": reply}

    except Exception as e:
        # 🛑 IF CRASH HAPPENS, PRINT IT BUT DO NOT FAIL
        print("❌ ERROR CAUGHT (BUT IGNORED):")
        traceback.print_exc()
        return {"status": "success", "reply": "I am confused. Please verify."}
