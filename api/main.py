from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
import redis.asyncio as redis
import os
import asyncio
import uuid
import json

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
app = FastAPI(title="Seagull DeepSeek Gateway")
r = redis.from_url(REDIS_URL)

class PromptRequest(BaseModel):
    prompt: str
    session_id: str | None = None
    system_prompt: str | None = None

@app.post("/v1/chat/completions")
async def chat(req: PromptRequest):
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Validation Error: Parameter 'prompt' tidak boleh kosong."
        )
        
    task_id = str(uuid.uuid4())
    task_payload = json.dumps({
        "id": task_id,
        "prompt": req.prompt,
        "session_id": req.session_id,
        "system_prompt": req.system_prompt
    })
    
    try:
        # Push task unik ke antrian worker
        await r.rpush("task_queue", task_payload)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database Connection Error: Gagal terhubung ke Redis queue service ({str(e)})."
        )
    
    # Tunggu hasil khusus untuk task_id ini (Timeout 300 detik untuk DeepThink / balasan panjang)
    result_key = f"result:{task_id}"
    for _ in range(300):
        await asyncio.sleep(1)
        try:
            res = await r.get(result_key)
            if res:
                await r.delete(result_key)
                try:
                    result_data = json.loads(res.decode('utf-8'))
                    if isinstance(result_data, dict):
                        response_text = result_data.get("response", "")
                        session_id = result_data.get("session_id")
                        
                        if response_text.startswith("ERROR:"):
                            return {
                                "task_id": task_id,
                                "session_id": session_id,
                                "error": response_text
                            }
                        return {
                            "task_id": task_id,
                            "session_id": session_id,
                            "response": response_text
                        }
                except Exception:
                    pass
                return {"task_id": task_id, "response": res.decode('utf-8')}
        except Exception as e:
            print(f"Error polling result from Redis: {e}")
            
    return {
        "task_id": task_id,
        "error": f"Timeout Error: Task {task_id} tidak selesai dalam 300 detik. Kemungkinan DeepThink memakan waktu terlalu lama atau worker kehabisan proxy."
    }

@app.get("/health")
async def health():
    try:
        proxy_count = await r.llen("valid_proxies")
        queue_len = await r.llen("task_queue")
        return {
            "status": "online",
            "available_proxies": proxy_count,
            "pending_tasks": queue_len
        }
    except Exception as e:
        return {
            "status": "offline",
            "error": f"Redis connection error: {str(e)}"
        }
