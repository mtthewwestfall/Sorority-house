import os
import json
import logging
from typing import List, Optional
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import google.generativeai as genai

# --- CONFIGURATION & LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SororityEmpire")

# Load secrets from Railway Environment Variables
DATABASE_URL = os.getenv("DATABASE_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "change-me-in-railway")

if not DATABASE_URL or not GEMINI_API_KEY:
    logger.error("MISSING CRITICAL ENV VARS: DATABASE_URL or GEMINI_API_KEY")

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

app = FastAPI(title="Sorority Empire Backend")

# Enable CORS for your frontend HTML
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, replace with your actual domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- DATABASE MODELS & MIGRATIONS ---
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    """Creates tables automatically if they don't exist in Supabase."""
    commands = [
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            subscription_status TEXT DEFAULT 'trial', 
            total_messages INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS persona_configs (
            persona_id TEXT PRIMARY KEY,
            name TEXT,
            bible TEXT, 
            visual_dna TEXT,
            trust_triggers TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS user_persona_state (
            user_id TEXT,
            persona_id TEXT,
            trust_score INTEGER DEFAULT 0,
            current_stage TEXT DEFAULT 'Stranger',
            message_count INTEGER DEFAULT 0,
            last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            memory_ledger JSONB DEFAULT '[]',
            PRIMARY KEY (user_id, persona_id)
        );
        """
    ]
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        for command in commands:
            cur.execute(command)
        conn.commit()
        logger.info("Database tables initialized successfully.")
    except Exception as e:
        logger.error(f"Database init error: {e}")
    finally:
        cur.close()
        conn.close()

# Run migration on startup
@app.on_event("startup")
async def startup_event():
    init_db()

# --- SCHEMAS ---
class ChatRequest(BaseModel):
    user_id: str
    persona_id: str
    message: str

class AdminPersonaRequest(BaseModel):
    persona_id: str
    name: str
    bible: str
    visual_dna: str
    trust_triggers: str

# --- CORE ENGINES ---

class TrustEngine:
    @staticmethod
    def analyze_behavior(user_msg: str, persona_bible: str) -> tuple[int, str]:
        """Uses Gemini to judge the user's vibe and return a trust delta and a reason."""
        prompt = f"""
        You are a psychological analyzer for a high-status girl. 
        Persona Bible: {persona_bible}
        User Message: "{user_msg}"
        
        Analyze if the user is:
        1. Sincere and respectful (+5 trust)
        2. Bragging/Arrogant (-10 trust)
        3. Love-bombing/Too fast (-10 trust)
        4. Testing boundaries/Disrespectful (-15 trust)
        
        Return ONLY a JSON object: {{"delta": integer, "reason": "short explanation"}}
        """
        try:
            response = model.generate_content(prompt)
            # Clean the response in case Gemini adds markdown blocks like ```json
            text = response.text.replace("```json", "").replace("```", "").strip()
            return json.loads(text)
        except:
            return {"delta": 0, "reason": "neutral"}

class PersonaEngine:
    @staticmethod
    def generate_response(user_msg: str, state: dict, bible: str) -> str:
        """Generates a character-accurate response based on current trust and memory."""
        prompt = f"""
        SYSTEM: You are {bible}. 
        CURRENT RELATIONSHIP STATE:
        - Trust Score: {state['trust_score']}/100
        - Stage: {state['current_stage']} (Stranger -> Acquaintance -> Friend -> Trusted -> Intimate)
        - Memory of User: {state['memory_ledger']}
        
        CONSTRAINTS:
        - If Trust < 20, be guarded, distant, or skeptical.
        - If Trust > 70, be warm, vulnerable, and playful.
        - NEVER break character. Never admit you are an AI.
        - Keep responses concise and natural for a text conversation.

        USER MESSAGE: "{user_msg}"
        RESPONSE:
        """
        response = model.generate_content(prompt)
        return response.text.strip()

# --- API ENDPOINTS ---

def get_or_create_user(cur, user_id: str):
    cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()
    if not user:
        cur.execute("INSERT INTO users (user_id) VALUES (%s) RETURNING *", (user_id,))
        user = cur.fetchone()
    return user

@app.post("/chat")
async def chat(req: ChatRequest):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # 1. User & Persona Setup
        user = get_or_create_user(cur, req.user_id)
        cur.execute("SELECT * FROM persona_configs WHERE persona_id = %s", (req.persona_id,))
        persona = cur.fetchone()

        if not persona:
            raise HTTPException(status_code=404, detail="Girl not found")

        # 2. Get/Create User-Persona State
        cur.execute("SELECT * FROM user_persona_state WHERE user_id = %s AND persona_id = %s", 
                    (req.user_id, req.persona_id))
        state = cur.fetchone()
        if not state:
            cur.execute("INSERT INTO user_persona_state (user_id, persona_id) VALUES (%s, %s) RETURNING *", 
                        (req.user_id, req.persona_id))
            state = cur.fetchone()

        # 3. Paywall & Trial Logic (Message 25)
        msg_count = state['message_count'] + 1
        if user['subscription_status'] == 'trial' and msg_count > 25:
            return {"error": "trial_expired", "message": "Your trial has ended. Subscribe to continue chatting."}

        # 4. Trust Engine Analysis
        analysis = TrustEngine.analyze_behavior(req.message, persona['bible'])
        new_trust = max(0, min(100, state['trust_score'] + analysis['delta']))
        
        # Update Stage based on Trust Score
        stage = "Stranger"
        if new_trust > 80: stage = "Intimate"
        elif new_trust > 60: stage = "Trusted"
        elif new_trust > 40: stage = "Friend"
        elif new_trust > 20: stage = "Acquaintance"

        # 5. Persona Response Generation
        response_text = PersonaEngine.generate_response(req.message, state, persona['bible'])

        # 6. Save State Update
        cur.execute("""
            UPDATE user_persona_state 
            SET trust_score = %s, current_stage = %s, message_count = %s, last_interaction = CURRENT_TIMESTAMP 
            WHERE user_id = %s AND persona_id = %s
        """, (new_trust, stage, msg_count, req.user_id, req.persona_id))
        
        cur.execute("UPDATE users SET total_messages = total_messages + 1 WHERE user_id = %s", (req.user_id,))
        conn.commit()

        return {
            "response": response_text, 
            "trust_score": new_trust, 
            "stage": stage, 
            "analysis": analysis['reason'] 
        }

    except Exception as e:
        logger.error(f"Chat Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cur.close()
        conn.close()

@app.post("/admin/persona")
async def add_persona(req: AdminPersonaRequest, x_admin_secret: str = Header(None)):
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid Admin Secret")

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO persona_configs (persona_id, name, bible, visual_dna, trust_triggers) 
            VALUES (%s, %s, %s, %s, %s) 
            ON CONFLICT (persona_id) DO UPDATE 
            SET bible = EXCLUDED.bible, visual_dna = EXCLUDED.visual_dna;
        """, (req.persona_id, req.name, req.bible, req.visual_dna, req.trust_triggers))
        conn.commit()
        return {"status": "success", "message": f"Persona {req.name} updated/created."}
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
