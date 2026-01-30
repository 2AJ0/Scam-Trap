# 🕸️ ScamTrap: AI Agentic Honeypot

**ScamTrap** is a high-performance, asynchronous AI agent designed to detect, engage, and analyze financial scammers. Acting as a "confused elderly victim," it wastes scammers' time while secretly extracting their payment details (UPI IDs, phone numbers) and reporting them to a central authority.

Built for the **GUVI Generative AI Hackathon**.

## 🚀 Key Features

* **🎭 Agentic Persona:** Uses `llama-3.1-8b-instant` (via Groq) to simulate a realistic, confused victim.
* **⚡ High Performance:** Built with **FastAPI** and **Asyncio** to handle hundreds of concurrent scammers without lag.
* **🔍 Intelligence Extraction:** Automatically detects and logs UPI IDs, Phone Numbers, and Phishing Links using Regex.
* **🛡️ Secure Architecture:** Uses environment variables for API keys to prevent credential theft.
* **🚨 Automated Reporting:** Instantly sends incident reports to the central server via background tasks.

## 🛠️ Tech Stack

* **Language:** Python 3.10+
* **Framework:** FastAPI (Uvicorn)
* **AI Engine:** Groq Cloud (Llama 3.1)
* **Networking:** HTTPX (Async Client)
* **Deployment:** Render / ngrok

## ⚙️ Installation & Local Setup

1.  **Clone the Repository**
    ```bash
    git clone [https://github.com/yourusername/scam-trap-final.git](https://github.com/yourusername/scam-trap-final.git)
    cd scam-trap-final
    ```

2.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Set Environment Variables**
    * **Option A (Terminal):**
        ```bash
        export GROQ_API_KEY="gsk_8A..."
        ```
    * **Option B (.env file):** Create a `.env` file and add your key there.

4.  **Run the Server**
    ```bash
    uvicorn main:app --reload
    ```
    The server will start at `http://127.0.0.1:8000`.

## ☁️ Deployment (Render)

This project is optimized for cloud deployment on **Render**.

1.  Push your code to **GitHub**.
2.  Create a new **Web Service** on Render.
3.  Connect your repository.
4.  **Build Command:** `pip install -r requirements.txt`
5.  **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
6.  **Environment Variables:**
    * Add `GROQ_API_KEY` with your actual secret key.

## 🧪 API Usage

**Endpoint:** `POST /chat`

**Headers:**
* `x-api-key`: `guvi-hackathon-pass`
* `Content-Type`: `application/json`

**Sample Body:**
```json
{
  "sessionId": "test-123",
  "message": {
    "sender": "scammer",
    "text": "Send money to upi@bank now!"
  },
  "conversationHistory": []
}
