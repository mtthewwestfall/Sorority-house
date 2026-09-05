import os
import json
from fastapi import FastAPI, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Dict, Optional
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

# Load environment variables from Railway/Codespaces
load_dotenv()

app = FastAPI(title="Sorority House Backend")

# --- DATABASE CONNECTION ---
# Railway provides DATABASE_URL automatically if you add a Postgres plugin
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_conn():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

# --- MODELS ---
class ChatRequest(BaseModel):
    user_id: str
    persona_id: str
    message: str

class AdminPersona(BaseModel):
    name: str
    system_prompt: str
    visual_dna: Dict
    behavioral_weights: Dict
    milestone_logic: Dict

# --- CORE LOGIC ENGINE ---
class PersonaEngine:
    @staticmethod
    def get_persona(conn, persona_id: str):
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM persona_configs WHERE id = %s", (persona_id,))
            return cur.fetchone()

    @staticmethod
    def update_trust(conn, user_id: str, persona_id: str, input_type: str, weight: int):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_persona_state SET trust_score = trust_score + %s WHERE user_id = %s AND persona_id = %s",
                (weight, user_id, persona_id)
            )
            conn.commit()

# --- API ENDPOINTS ---

@app.get("/health")
async def health():
    return {"status": "online", "message": "Sorority House is open"}

@app.post("/chat")
async def chat(request: ChatRequest):
    conn = get_db_conn()
    try:
        # 1. Fetch User & State
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (request.user_id,))
            user = cur.fetchone()
            
            cur.execute("SELECT * FROM user_persona_state WHERE user_id = %s AND persona_id = %s", 
                        (request.user_id, request.persona_id))
            state = cur.fetchone()

        # 2. Paywall Logic (The Message 25 Gate)
        if user['subscription_status'] == 'trial' and user['trial_message_count'] >= 25:
            raise HTTPException(status_code=402, detail="Trial ended. Please subscribe to keep talking.")

        # 3. Load Persona DNA
        config = PersonaEngine.get_persona(conn, request.persona_id)
        if not config:
            raise HTTPException(status_code=404, detail="Girl not found in house.")

        # 4. Behavioral Analysis (Simulation of the "Boaster Trap")
        # In full production, we'd pass the message to a small LLM to classify it as 'boast', 'honest', etc.
        input_type = "neutral" 
        if " i " in request.message.lower() or "best" in request.message.lower(): 
            input_type = "boast" # Simplified logic for the demo
        
        weight = config['behavioral_weights'].get(input_type, 0)
        PersonaEngine.update_trust(conn, request.user_id, request.persona_id, input_type, weight)

        # 5. Construct LLM Prompt
        prompt = f"{config['system_prompt']}\n\nUser Trust Level: {state['trust_score']}\nMilestone: {state['current_milestone']}"
        
        # HERE: You would call your LLM API (Anthropic/OpenAI) using the prompt and request.message
        # response = call_llm(prompt, request.message) 
        response = f"[Simulated Response from {config['name']}] I hear you. (Trust adjusted by {weight})"

        # 6. Update Message Counters
        with conn.cursor() as cur:
            if user['subscription_status'] == 'trial':
                cur.execute("UPDATE users SET trial_message_count = trial_message_count + 1 WHERE id = %s", (request.user_id,))
            else:
                cur.execute("UPDATE users SET subscription_message_count = subscription_message_count + 1 WHERE id = %s", (request.user_id,))
            conn.commit()

        return {"response": response, "trust_adjustment": weight}
    finally:
        conn.close()

@app.post("/admin/persona")
async def add_persona(persona: AdminPersona, secret: str):
    if secret != os.getenv("ADMIN_SECRET"): 
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO persona_configs (name, system_prompt, visual_dna, behavioral_weights, milestone_logic) VALUES (%s, %s, %s, %s, %s)",
                (persona.name, persona.system_prompt, json.dumps(persona.visual_dna), 
                 json.dumps(persona.behavioral_weights), json.dumps(persona.milestone_logic))
            )
            conn.commit()
        return {"status": f"{persona.name} has been added to the house."}
    finally:
        conn.close()
