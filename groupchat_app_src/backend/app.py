import os
import asyncio
import httpx
from typing import Optional, List
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from dotenv import load_dotenv

# Import local modules
from db import SessionLocal, init_db, User, Message
from auth import get_password_hash, verify_password, create_access_token, get_current_user_token
from websocket_manager import ConnectionManager

# Load environment variables
if not load_dotenv():
    load_dotenv("../.env")

# App settings
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))

# LLM settings
LLM_API_BASE = os.getenv("LLM_API_BASE", "http://127.0.0.1:11434")
# Hardcoded to match the user's installed model, ignoring incorrect .env values from PDF
LLM_MODEL = "llama3.1:8b"

app = FastAPI(title="Group Chat with AI Bot")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = ConnectionManager()

# --------- Schemas ---------
class AuthPayload(BaseModel):
    username: str
    password: str

class MessagePayload(BaseModel):
    content: str

# --------- Dependencies ---------
async def get_db() -> AsyncSession:
    """
    Database Session Management
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        await session.close()

# --------- AI and Message Utilities ---------

async def test_ollama_connection():
    """
    Test Ollama connection on startup
    """
    print("="*50)
    print(f"[DEBUG] Initializing AI module...")
    print(f"[DEBUG] Target Model: {LLM_MODEL}")
    
    url = f"http://127.0.0.1:11434/"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=5.0)
            if response.status_code == 200:
                print(f"[DEBUG] SUCCESS: Connected to Ollama service!")
            else:
                print(f"[DEBUG] ERROR: Ollama returned status code: {response.status_code}")
        except Exception as e:
            print(f"[DEBUG] ERROR: Could not connect to Ollama: {str(e)}")
            print(f"[DEBUG] Please ensure 'ollama serve' is running.")
    print("="*50)

async def call_ollama_ai(user_query: str):
    """
    Call local Ollama API using the native /api/chat endpoint
    """
    targets = [
        "http://127.0.0.1:11434/api/chat", 
        "http://localhost:11434/api/chat",
        "http://0.0.0.0:11434/api/chat"
    ]
    
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful group chat assistant."},
            {"role": "user", "content": user_query}
        ],
        "stream": False
    }

    async with httpx.AsyncClient() as client:
        for url in targets:
            try:
                print(f"[DEBUG] Attempting AI connection: {url} with model '{LLM_MODEL}'")
                response = await client.post(url, json=payload, timeout=90.0)
                
                if response.status_code == 200:
                    data = response.json()
                    return data['message']['content']
                
                # If we get a 404, capture the exact error message from Ollama
                error_body = response.text
                print(f"[DEBUG] WARNING: {url} returned status {response.status_code}. Response body: {error_body}")
                
                if "not found" in error_body.lower():
                    return f"(AI Error) Model '{LLM_MODEL}' not found. Please run 'ollama pull {LLM_MODEL}' in terminal."
                    
            except Exception as e:
                print(f"[DEBUG] FAILED: {url} connection error: {str(e)}")
                continue
        
        return f"(AI Error) All connection attempts failed. Last attempted model: {LLM_MODEL}. Check terminal DEBUG logs."

async def broadcast_single_message(session: AsyncSession, msg: Message):
    """
    Broadcast message to all WebSocket connections
    """
    username = "unknown"
    if msg.user_id:
        u_res = await session.execute(select(User).where(User.id == msg.user_id))
        u = u_res.scalar_one_or_none()
        username = u.username if u else "unknown"
    
    await manager.broadcast({
        "type": "message",
        "message": {
            "id": msg.id,
            "username": "LLM Bot" if msg.is_bot else username,
            "content": msg.content,
            "is_bot": msg.is_bot,
            "created_at": str(msg.created_at)
        }
    })

async def maybe_answer_with_llm(content: str):
    """
    Check if message triggers AI
    """
    if not content.strip().endswith("?"):
        return

    print(f"[DEBUG] Question mark detected, preparing to call AI...")
    reply_text = await call_ollama_ai(content)
    
    async with SessionLocal() as session:
        try:
            bot_msg = Message(user_id=None, content=reply_text, is_bot=True)
            session.add(bot_msg)
            await session.commit()
            await session.refresh(bot_msg)
            await broadcast_single_message(session, bot_msg)
            print(f"[DEBUG] AI reply processed successfully.")
        except Exception as e:
            print(f"[ERROR] AI message storage failed: {e}")
        finally:
            await session.close()

# --------- Routes ---------

@app.on_event("startup")
async def on_startup():
    await init_db()
    # Test connection immediately on startup
    asyncio.create_task(test_ollama_connection())

@app.post("/api/signup")
async def signup(payload: AuthPayload, session: AsyncSession = Depends(get_db)):
    existing = await session.execute(select(User).where(User.username == payload.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")
    u = User(username=payload.username, password_hash=get_password_hash(payload.password))
    session.add(u)
    await session.commit()
    token = create_access_token({"sub": u.username})
    return {"ok": True, "token": token}

@app.post("/api/login")
async def login(payload: AuthPayload, session: AsyncSession = Depends(get_db)):
    res = await session.execute(select(User).where(User.username == payload.username))
    u = res.scalar_one_or_none()
    if not u or not verify_password(payload.password, u.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": u.username})
    return {"ok": True, "token": token}

@app.get("/api/messages")
async def get_messages(limit: int = 50, session: AsyncSession = Depends(get_db)):
    res = await session.execute(
        select(Message).order_by(desc(Message.created_at)).limit(limit)
    )
    items = list(reversed(res.scalars().all()))
    
    out = []
    for m in items:
        username = "unknown"
        if not m.is_bot and m.user_id:
            u_res = await session.execute(select(User).where(User.id == m.user_id))
            u = u_res.scalar_one_or_none()
            username = u.username if u else "unknown"
            
        out.append({
            "id": m.id,
            "username": "LLM Bot" if m.is_bot else username,
            "content": m.content,
            "is_bot": m.is_bot,
            "created_at": str(m.created_at)
        })
    return {"messages": out}

@app.post("/api/messages")
async def post_message(payload: MessagePayload, username: str = Depends(get_current_user_token), session: AsyncSession = Depends(get_db)):
    res = await session.execute(select(User).where(User.username == username))
    u = res.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=401, detail="Invalid user")
    
    m = Message(user_id=u.id, content=payload.content, is_bot=False)
    session.add(m)
    await session.commit()
    await session.refresh(m)
    await broadcast_single_message(session, m)
    
    asyncio.create_task(maybe_answer_with_llm(payload.content))
    
    return {"ok": True, "id": m.id}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_json({"type": "ack", "echo": data})
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Mount static files
app.mount("/", StaticFiles(directory="../frontend", html=True), name="static")