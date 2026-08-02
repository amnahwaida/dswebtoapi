from fastapi import FastAPI, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import redis.asyncio as redis
import os
import asyncio
import uuid
import json

import re

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
app = FastAPI(title="Seagull DeepSeek Gateway")
r = redis.from_url(REDIS_URL)

def format_for_whatsapp(text: str) -> str:
    """Format teks Markdown menjadi teks siap kirim untuk WhatsApp."""
    if not text:
        return ""
    # 1. Hapus sisa-sisa header pemikir / search noise DeepSeek jika ada
    text = re.sub(r'^(Thought for \d+ seconds|Read \d+ web pages|Searched \d+ sites).*\n?', '', text, flags=re.MULTILINE)
    # 2. Ubah Markdown Headers (# Header, ## Header, ### Header) menjadi *Header* (Bold WhatsApp)
    text = re.sub(r'^(#{1,6})\s+(.+)$', r'*\2*', text, flags=re.MULTILINE)
    # 3. Ubah Markdown Bold (**text** atau __text__) menjadi WhatsApp Bold (*text*)
    text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text)
    text = re.sub(r'__(.*?)__', r'*\1*', text)
    # 4. Ubah Markdown Strikethrough (~~text~~) menjadi WhatsApp Strikethrough (~text~)
    text = re.sub(r'~~(.*?)~~', r'~\1~', text)
    # 5. Ubah Bullet points (- atau *) menjadi titik bullet WhatsApp (• )
    text = re.sub(r'^[ \t]*[*\-]\s+', r'• ', text, flags=re.MULTILINE)
    # 6. Rapikan baris kosong berlebihan
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

class PromptRequest(BaseModel):
    prompt: str
    session_id: str | None = None
    system_prompt: str | None = None
    stream: bool | None = False

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
        "system_prompt": req.system_prompt,
        "stream": req.stream
    })
    
    try:
        # Push task unik ke antrian worker
        await r.rpush("task_queue", task_payload)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database Connection Error: Gagal terhubung ke Redis queue service ({str(e)})."
        )

    # 1. STREAMING RESPONSE MODE (Server-Sent Events / SSE)
    if req.stream:
        async def stream_generator():
            pubsub = r.pubsub()
            await pubsub.subscribe(f"stream:{task_id}")
            timeout_counter = 0
            try:
                # Event koneksi dibuka
                init_msg = {
                    "task_id": task_id,
                    "session_id": req.session_id,
                    "status": "started"
                }
                yield f"data: {json.dumps(init_msg)}\n\n"
                
                while True:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message:
                        timeout_counter = 0
                        data = json.loads(message['data'].decode('utf-8'))
                        msg_type = data.get("type")
                        
                        if msg_type == "chunk":
                            full_txt = data.get("full_text", "")
                            chunk_payload = {
                                "task_id": task_id,
                                "delta": data.get("delta", ""),
                                "text": full_txt,
                                "whatsapp_text": format_for_whatsapp(full_txt)
                            }
                            yield f"data: {json.dumps(chunk_payload)}\n\n"
                        elif msg_type == "done":
                            resp_text = data.get("response", "")
                            done_payload = {
                                "task_id": task_id,
                                "session_id": data.get("session_id"),
                                "response": resp_text,
                                "whatsapp_text": format_for_whatsapp(resp_text),
                                "status": "completed"
                            }
                            yield f"data: {json.dumps(done_payload)}\n\n"
                            yield "data: [DONE]\n\n"
                            break
                        elif msg_type == "error":
                            err_payload = {
                                "task_id": task_id,
                                "error": data.get("error")
                            }
                            yield f"data: {json.dumps(err_payload)}\n\n"
                            yield "data: [DONE]\n\n"
                            break
                    else:
                        timeout_counter += 1
                        if timeout_counter >= 300:
                            timeout_payload = {
                                "task_id": task_id,
                                "error": "Timeout Error: Task tidak selesai dalam 300 detik."
                            }
                            yield f"data: {json.dumps(timeout_payload)}\n\n"
                            yield "data: [DONE]\n\n"
                            break
            finally:
                await pubsub.unsubscribe(f"stream:{task_id}")
                await pubsub.close()

        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    
    # 2. NON-STREAMING RESPONSE MODE (BLOCKING POLL RESULT KEY)
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
                            "response": response_text,
                            "whatsapp_text": format_for_whatsapp(response_text)
                        }
                except Exception:
                    pass
                raw_str = res.decode('utf-8')
                return {
                    "task_id": task_id,
                    "response": raw_str,
                    "whatsapp_text": format_for_whatsapp(raw_str)
                }
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
