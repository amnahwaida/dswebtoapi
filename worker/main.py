import asyncio
import redis.asyncio as redis
import os
import random
import json
from playwright.async_api import async_playwright

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
SCREENSHOT_DIR = os.getenv("SCREENSHOT_DIR", "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

async def take_screenshot(page, name):
    """Simpan screenshot halaman untuk visual inspeksi progress."""
    try:
        path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
        await page.screenshot(path=path)
        print(f"📸 Screenshot tersimpan: {path}")
    except Exception as e:
        print(f"Gagal mengambil screenshot {name}: {e}")

async def get_proxy(r):
    """Ambil random proxy valid dari Redis."""
    length = await r.llen("valid_proxies")
    if length == 0:
        return None
    idx = random.randint(0, length - 1)
    return await r.lindex("valid_proxies", idx)

async def process_request(prompt, proxy_str, session_id=None, system_prompt=None, task_id=None, r=None):
    """Eksekusi browser dengan proxy, tangani auto-redirect login, dan tangkap response via CDP/Event."""
    sys_instruction = system_prompt
    
    # 1. Jika tidak ada dari API, coba baca dari file system_prompt.txt / system_prompt.md
    if not sys_instruction:
        for filepath in ["system_prompt.txt", "system_prompt.md", "/app/system_prompt.txt", "../system_prompt.txt"]:
            if os.path.exists(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        # Abaikan baris komentar (#) jika hanya file default template
                        lines = [line for line in content.splitlines() if not line.strip().startswith("#")]
                        cleaned = "\n".join(lines).strip()
                        if cleaned:
                            sys_instruction = cleaned
                            break
                except Exception as e:
                    print(f"Error membaca {filepath}: {e}")
                    
    # 2. Fallback terakhir ke variabel DEFAULT_SYSTEM_PROMPT di .env
    if not sys_instruction:
        sys_instruction = os.getenv("DEFAULT_SYSTEM_PROMPT", "").strip()

    if not session_id and sys_instruction:
        print(f"Menyisipkan system prompt identitas AI ({len(sys_instruction)} karakter)...")
        prompt = f"[System Instruction]:\n{sys_instruction}\n\n[User Question]:\n{prompt}"

    async with async_playwright() as p:
        proxy_config = {"server": f"http://{proxy_str}"} if proxy_str else None
        
        print(f"Launching browser (Headless: {HEADLESS})...")
        browser = await p.chromium.launch(
            headless=HEADLESS,
            proxy=proxy_config,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage'
            ]
        )
        
        context_args = {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "viewport": {"width": 1280, "height": 800},
            "locale": "en-US",
            "extra_http_headers": {
                "Accept-Language": "en-US,en;q=0.9"
            }
        }
        
        state_file = "auth_state.json"
        if os.path.exists(state_file):
            context_args["storage_state"] = state_file
            
        context = await browser.new_context(**context_args)
        
        # Override navigator.webdriver untuk meyakinkan browser bukan otomasi
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)
        
        page = await context.new_page()
        captured_response = []
        error_msg = None
        current_session_id = session_id
        
        # Interception: Tangkap response SSE/JSON dari endpoint chat completion khusus
        async def handle_response(response):
            if "completion" in response.url and response.status == 200:
                try:
                    text = await response.text()
                    captured_response.append(text)
                except Exception:
                    pass
                    
        page.on("response", handle_response)
        
        try:
            target_url = f"https://chat.deepseek.com/a/chat/s/{session_id}" if session_id else "https://chat.deepseek.com"
            print(f"Navigating to {target_url} ...")
            await page.goto(target_url, timeout=20000, wait_until="domcontentloaded")
            
            # Tunggu elemen UI (baik Chat Input maupun Form Login) selesai dirender oleh SPA React
            try:
                print("Menunggu antarmuka utama (Chat Input atau Sign-In Form)...")
                await page.wait_for_selector(
                    'textarea, #chat-input, div[contenteditable="true"], input[type="password"], .ds-sign-in-form__main, input[placeholder*="Phone number"]',
                    timeout=20000
                )
            except Exception:
                pass
                
            await page.wait_for_timeout(1000)
            await take_screenshot(page, "1_page_loaded")
            
            # Cek apakah terhalang Cloudflare Turnstile / Challenge Overlay
            cf_overlay = await page.query_selector('#cf-overlay, #cf-turnstile')
            if cf_overlay and await cf_overlay.is_visible():
                await take_screenshot(page, "error_cloudflare")
                raise Exception("Terhalang Cloudflare Turnstile / Captcha. Proxy terdeteksi sebagai bot.")

            # Deteksi apakah ter-redirect ke halaman login / sign_in
            is_login_page = "sign_in" in page.url or "sign-in" in page.url or (await page.query_selector('input[type="password"]') is not None) or (await page.query_selector('.ds-sign-in-form__main') is not None)
            
            if is_login_page:
                print("Terdeteksi redirect ke Halaman Login. Mengatur proses sign-in...")
                await take_screenshot(page, "2_login_page")
                email = os.getenv("DEEPSEEK_EMAIL", "")
                password = os.getenv("DEEPSEEK_PASSWORD", "")
                
                if not email or not password or "example.com" in email or "your_password" in password:
                    await take_screenshot(page, "error_credentials_missing")
                    raise Exception("Ter-redirect ke halaman login, tetapi DEEPSEEK_EMAIL atau DEEPSEEK_PASSWORD di .env belum diisi dengan akun DeepSeek yang valid.")

                # Cek jika form dalam mode SMS Verification Code/Phone, coba switch ke mode Password/Email Login
                switch_pwd_btn = await page.query_selector(
                    'div:has-text("Password"), span:has-text("Password"), div:has-text("Log in with Password"), div:has-text("Email")'
                )
                if switch_pwd_btn and await switch_pwd_btn.is_visible() and (await page.query_selector('input[type="password"]') is None):
                    print("Mengklik tombol switch ke Password Login mode...")
                    await switch_pwd_btn.click()
                    await page.wait_for_timeout(1000)
                
                # Mengisi Email / Phone
                email_input = await page.wait_for_selector('input[placeholder*="Phone number"], input[placeholder*="email"], input[type="text"]', timeout=10000)
                if email_input:
                    await email_input.fill(email)
                
                # Mengisi Password (jika ada)
                pwd_input = await page.wait_for_selector('input[type="password"]', timeout=10000)
                if pwd_input:
                    await pwd_input.fill(password)
                else:
                    await take_screenshot(page, "error_phone_verification_mode")
                    raise Exception("DeepSeek meminta verifikasi nomor HP (SMS OTP) karena lokasi IP proxy. Gunakan proxy wilayah US/Global atau pastikan akun sudah terhubung.")
                
                await take_screenshot(page, "2_login_form_filled")
                
                # Klik Tombol Log in
                login_btn = await page.wait_for_selector('div[role="button"]:has-text("Log in"), button:has-text("Log in"), .ds-button:has-text("Log in")', timeout=10000)
                if login_btn:
                    await login_btn.click()
                
                # Tunggu redirect keluar dari halaman sign_in
                try:
                    await page.wait_for_url(lambda url: "sign_in" not in url and "sign-in" not in url, timeout=20000)
                    await page.wait_for_timeout(3000)
                    await take_screenshot(page, "3_after_login")
                except Exception:
                    await take_screenshot(page, "error_login_failed")
                    raise Exception("Gagal login: Kredensial salah atau terhalang Captcha/OTP pada login.")
                
                # Simpan session / storage state ke auth_state.json untuk reuse di request berikutnya
                try:
                    await context.storage_state(path=state_file)
                    print(f"Auth state berhasil disimpan ke {state_file}")
                except Exception as e:
                    print(f"Gagal menyimpan auth state: {e}")
            
            # Jika request TIDAK membawa session_id, klik "New chat" jika saat ini terbuka percakapan lama
            if not session_id:
                try:
                    new_chat_btn = await page.query_selector('div:has-text("New chat"), span:has-text("New chat")')
                    if new_chat_btn and await new_chat_btn.is_visible():
                        print("Request Chat Baru: Mengklik tombol 'New chat'...")
                        await new_chat_btn.click()
                        await page.wait_for_timeout(1000)
                except Exception as e:
                    print(f"Gagal mengklik tombol New chat: {e}")

            # Memastikan sudah di halaman utama chat & mencari elemen input prompt
            print("Mencari elemen input chat...")
            chat_input = await page.wait_for_selector(
                'textarea[placeholder*="Message DeepSeek"], textarea, #chat-input, div[contenteditable="true"]',
                timeout=20000,
                state="visible"
            )
            
            if not chat_input:
                await take_screenshot(page, "error_no_chat_input")
                raise Exception("Elemen input chat tidak ditemukan di halaman.")
                
            # Pastikan mode DeepThink (R1 Reasoning) selalu aktif (aria-pressed="true")
            try:
                deepthink_btn = await page.query_selector('.ds-toggle-button:has-text("DeepThink")')
                if deepthink_btn:
                    is_pressed = await deepthink_btn.get_attribute("aria-pressed")
                    if is_pressed == "false":
                        print("Mengaktifkan mode DeepThink (R1)...")
                        await deepthink_btn.click()
                        await page.wait_for_timeout(300)
                    else:
                        print("Mode DeepThink (R1) sudah aktif.")
            except Exception as e:
                print(f"Warning: Gagal memverifikasi tombol DeepThink: {e}")

            # Catat jumlah dan teks pesan balasan yang sudah ada di halaman sebelum prompt dikirim
            initial_elems = await page.query_selector_all('.ds-assistant-message-main-content, .ds-markdown')
            initial_count = len(initial_elems)
            initial_last_text = (await initial_elems[-1].inner_text()).strip() if initial_elems else ""

            await chat_input.click()
            await chat_input.fill(prompt)
            await page.wait_for_timeout(500)
            await take_screenshot(page, "4_prompt_filled")
            
            # Kirim prompt (klik tombol submit atau press Enter)
            send_btn = await page.query_selector('div[role="button"].ds-icon-button, button[type="submit"], .ds-send-button, div[role="button"]:has-text("Send")')
            if send_btn and await send_btn.is_visible():
                await send_btn.click()
            else:
                await chat_input.press("Enter")
                
            print(f"Prompt berhasil dikirim (Initial history messages: {initial_count}). Menunggu balasan AI baru...")
            await page.wait_for_timeout(1500)
            await take_screenshot(page, "5_prompt_sent")
            
            # Fast Polling teks balasan BARU dari DOM (interval 250ms)
            final_dom_text = ""
            previous_text = ""
            unchanged_count = 0

            for _ in range(1200): # 1200 * 250ms = 300 detik max (sesuai API timeout)
                try:
                    elems = await page.query_selector_all('.ds-assistant-message-main-content, .ds-markdown')
                    # Pastikan elemen balasan BARU telah muncul (jumlah bertambah ATAU teks elemen terakhir berbeda dari sebelum dikirim)
                    if len(elems) > initial_count or (elems and (await elems[-1].inner_text()).strip() != initial_last_text):
                        last_elem = elems[-1]
                        
                        # Ekstrak teks bersih tanpa bagian "Read web pages / Thinking" dari DeepSeek Search
                        current_text = await last_elem.evaluate("""el => {
                            const clone = el.cloneNode(true);
                            // Hapus elemen pemikir / web search header jika ada
                            const noise = clone.querySelectorAll('._74c0879, .c2b72bb8, ._60aa7fb, ._8f7678d');
                            noise.forEach(n => n.remove());
                            return clone.innerText.trim();
                        }""")
                        
                        if current_text and current_text != initial_last_text:
                            # Cek indikator apakah AI masih aktif mengetik (tombol Stop)
                            stop_btn = await page.query_selector('div[role="button"]:has-text("Stop"), .ds-stop-button, svg rect[width="12"][height="12"]')
                            is_generating = stop_btn and await stop_btn.is_visible()
                            
                            if current_text != previous_text:
                                # Hitung delta jika teks baru diawali teks lama
                                if previous_text and current_text.startswith(previous_text):
                                    delta = current_text[len(previous_text):]
                                else:
                                    delta = current_text
                                    
                                previous_text = current_text
                                unchanged_count = 0
                                
                                # Publish chunk real-time ke Redis Pub/Sub jika task_id dan r tersedia
                                if r and task_id and delta:
                                    try:
                                        await r.publish(f"stream:{task_id}", json.dumps({
                                            "type": "chunk",
                                            "delta": delta,
                                            "full_text": current_text
                                        }))
                                    except Exception as pub_err:
                                        print(f"Error publishing stream chunk: {pub_err}")
                            else:
                                unchanged_count += 1
                                # Selesai jika tombol Stop hilang DAN teks tidak berubah selama min 1.5 detik (6x check @ 250ms = 1.5s)
                                if not is_generating and unchanged_count >= 6:
                                    final_dom_text = current_text
                                    break
                                elif unchanged_count >= 12:
                                    final_dom_text = current_text
                                    break
                except Exception:
                    pass
                await page.wait_for_timeout(250)

            if final_dom_text:
                print(f"✅ Balasan AI berhasil diekstrak dari DOM ({len(final_dom_text)} karakter).")
                await take_screenshot(page, "6_response_received")
                captured_response = [final_dom_text]
            elif captured_response:
                # Jika DOM extraction gagal tapi ada network stream, coba ekstrak teks bersih dari SSE raw stream
                print("Parsing fallback dari captured network response SSE...")
                parsed_text = ""
                for chunk in captured_response:
                    for line in chunk.splitlines():
                        if line.startswith("data:"):
                            try:
                                payload = json.loads(line[5:].strip())
                                # Cek jika ada patch operasi append teks
                                if isinstance(payload, dict):
                                    v = payload.get("v")
                                    if isinstance(v, str):
                                        parsed_text += v
                                    elif isinstance(v, dict):
                                        resp = v.get("response", {})
                                        frags = resp.get("fragments", [])
                                        for f in frags:
                                            if f.get("type") == "RESPONSE":
                                                parsed_text += f.get("content", "")
                            except Exception:
                                pass
                if parsed_text.strip():
                    captured_response = [parsed_text.strip()]
            else:
                await take_screenshot(page, "error_no_captured_response")
                error_msg = "ERROR: Tidak ada respon balasan AI yang berhasil diekstrak. Kemungkinan proxy mati atau stream terputus."
                
            if "/s/" in page.url:
                try:
                    current_session_id = page.url.split("/s/")[1].split("?")[0]
                except Exception:
                    pass

        except Exception as e:
            print(f"Browser error di process_request: {e}")
            try:
                await take_screenshot(page, "error_last_state")
            except Exception:
                pass
            error_msg = f"ERROR: {str(e)}"
        finally:
            await browser.close()
            
        return captured_response, error_msg, current_session_id

async def worker_loop():
    r = redis.from_url(REDIS_URL, socket_timeout=10.0)
    print("海鸥 Worker ONLINE. Menunggu task...")
    while True:
        # Blocking pop dari task_queue dengan penanganan TimeoutError
        try:
            task = await r.blpop("task_queue", timeout=5)
        except (redis.exceptions.TimeoutError, asyncio.TimeoutError):
            task = None
        except Exception as e:
            print(f"Redis connection error: {e}")
            await asyncio.sleep(2)
            continue

        if task:
            raw_task = task[1].decode('utf-8')
            task_id = None
            prompt = raw_task
            session_id = None
            system_prompt = None

            try:
                task_data = json.loads(raw_task)
                if isinstance(task_data, dict):
                    task_id = task_data.get("id")
                    prompt = task_data.get("prompt", raw_task)
                    session_id = task_data.get("session_id")
                    system_prompt = task_data.get("system_prompt")
            except Exception:
                pass

            if not prompt:
                continue

            success = False
            max_retries = 3
            last_err = "ERROR: Failed after proxy retries."

            for attempt in range(max_retries):
                proxy = await get_proxy(r)
                if not proxy:
                    print("Tidak ada proxy valid tersisa di Redis.")
                    last_err = "ERROR: Tidak ada proxy valid tersisa di Redis."
                    break

                proxy_str = proxy.decode('utf-8')
                print(f"[{task_id or 'NO_ID'}] Attempt {attempt + 1}/{max_retries} processing prompt: '{prompt[:30]}...' (session: {session_id or 'NEW'}) dengan proxy: {proxy_str}")
                
                responses, err, cur_session_id = await process_request(
                    prompt, proxy_str, session_id=session_id, system_prompt=system_prompt, task_id=task_id, r=r
                )
                
                if responses:
                    res_text = str(responses[0])
                    result_payload = json.dumps({
                        "response": res_text,
                        "session_id": cur_session_id
                    })
                    if task_id:
                        await r.setex(f"result:{task_id}", 3600, result_payload)
                        try:
                            await r.publish(f"stream:{task_id}", json.dumps({
                                "type": "done",
                                "session_id": cur_session_id,
                                "response": res_text
                            }))
                        except Exception as e:
                            print(f"Error publishing stream done: {e}")
                    else:
                        await r.rpush("result_queue", result_payload)
                    success = True
                    break
                else:
                    last_err = err
                    print(f"Attempt {attempt + 1} gagal: {err}")
                    if any(kw in str(err) for kw in ["ERR_TIMED_OUT", "ERR_PROXY", "ERR_CONNECTION", "Timeout"]):
                        print(f"🗑️ Menghapus proxy mati ({proxy_str}) dari Redis...")
                        try:
                            await r.lrem("valid_proxies", 0, proxy)
                        except Exception as e:
                            print(f"Gagal menghapus proxy dari Redis: {e}")

            if not success:
                err_text = last_err or "ERROR: Max retries exceeded."
                if task_id:
                    await r.setex(f"result:{task_id}", 3600, err_text)
                    try:
                        await r.publish(f"stream:{task_id}", json.dumps({
                            "type": "error",
                            "error": err_text
                        }))
                    except Exception as e:
                        print(f"Error publishing stream error: {e}")
                else:
                    await r.rpush("result_queue", err_text)
        else:
            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(worker_loop())
