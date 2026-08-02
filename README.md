# Seagull DeepSeek Web-to-API Gateway

Seagull DeepSeek Gateway adalah layanan API high-performance yang mengubah antarmuka Web DeepSeek Chat (`chat.deepseek.com`) menjadi REST API berstandar OpenAI/Cloud. Dibuat menggunakan **FastAPI**, **Redis Queue**, **Playwright (Browser Automation)**, dan terintegrasi dengan **Cloudflare Tunnel**.

---

## 🚀 Fitur Utama

- **OpenAI Compatible Endpoint**: Format request `/v1/chat/completions` yang mudah diintegrasikan.
- **Multi-Turn Chat Continuation (`session_id`)**: Mendukung percakapan berlanjut secara presisi.
- **Custom System Prompt / Identitas AI (3 Metode)**: Mendukung pengubahan persona/karakter AI dari request `curl`, file `system_prompt.txt`, atau `.env`.
- **Auto-Enable DeepThink (R1 Reasoning)**: Otomatis mengaktifkan fitur penalaran mendalam DeepThink pada setiap percakapan.
- **Self-Healing Proxy Scraper & Rotary**: Mengakses web via antrian proxy yang terverifikasi dan secara otomatis menghapus proxy yang mati/lambat.
- **Cloudflare Tunnel Ready**: Siap dipublikasikan ke domain/subdomain HTTPS publik secara langsung via Docker Compose.

---

## 📖 Cara Mengubah Identitas / System Prompt AI

Anda dapat menentukan karakter, identitas, atau instruksi khusus (*system prompt*) untuk AI melalui 3 cara fleksibel:

### 1. Metode A: Dinamis per Request `curl` (Rekomendasi per Percakapan)
Sertakan parameter `"system_prompt"` pada body JSON ketika melakukan request `curl`. Instruksi ini akan dikirimkan di awal percakapan baru.

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "system_prompt": "Kamu adalah Antigravity AI, pakar Python senior yang selalu menjawab singkat, formal, dan menyertakan contoh kode.",
    "prompt": "Siapa kamu dan apa keahlianmu?"
  }'
```

---

### 2. Metode B: Menggunakan File `system_prompt.txt` (Untuk System Prompt Sangat Panjang)
Jika instruksi identitas AI Anda sangat panjang (berisi aturan khusus, format Markdown, poin-poin, atau persona rumit):

1. Edit file [`system_prompt.txt`](./system_prompt.txt) yang ada di direktori utama proyek.
2. Tuliskan identitas/instruksi lengkap Anda di dalamnya:

```markdown
Kamu adalah Seagull AI, asisten keamanan siber yang ramah dan serba tahu.

Aturan Respon:
1. Jawab selalu menggunakan Bahasa Indonesia.
2. Gunakan format Markdown yang rapi dengan poin-poin.
3. Berikan contoh kode praktis jika ditanya mengenai skrip otomatisasi.
```

3. Simpan file. Setiap request `curl` percakapan baru akan otomatis membaca dan menyisipkan isi file ini!

---

### 3. Metode C: Menggunakan File `.env` (Global Default)
Buka file `.env` dan tambahkan variabel `DEFAULT_SYSTEM_PROMPT`:

```env
DEFAULT_SYSTEM_PROMPT=Kamu adalah Seagull AI, asisten ramah yang selalu menjawab dalam Bahasa Indonesia.
```

---

### 🎯 Urutan Prioritas System Prompt:
1. Parameter `"system_prompt"` dari request JSON `curl` (Prioritas Utama).
2. Isi file [`system_prompt.txt`](./system_prompt.txt) (jika terisi).
3. Variabel `DEFAULT_SYSTEM_PROMPT` di file `.env`.

---

## 💬 Contoh Penggunaan API

### 1. Memulai Chat Baru (New Chat)
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Bagaimana cara kerja Docker Compose?"
  }'
```

**Respon JSON:**
```json
{
  "task_id": "a88f1ec7-de69-4944-9751-0ac1c4f1bb75",
  "session_id": "73ec9ead-3f3a-4f21-ad5e-f26ec3d7560f",
  "response": "## Pengenalan\nDocker Compose adalah alat...",
  "whatsapp_text": "*Pengenalan*\nDocker Compose adalah alat..."
}
```

### 2. Melanjutkan Percakapan (Multi-Turn Chat)
Gunakan `session_id` dari respon sebelumnya untuk melanjutkan percakapan:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "73ec9ead-3f3a-4f21-ad5e-f26ec3d7560f",
    "prompt": "Berikan contoh file docker-compose.yaml sederhananya!"
  }'
```

### 3. Real-time Streaming Response (Server-Sent Events / SSE)
Tambahkan `"stream": true` dan gunakan flag `-N` (unbuffered) pada `curl` untuk menerima potongan teks secara real-time saat AI sedang mengetik:

```bash
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "stream": true,
    "prompt": "Jelaskan konsep dasar Quantum Computing dalam 3 paragraf!"
  }'
```

**Output Stream (SSE):**
```text
data: {"task_id": "a88f1ec7-...", "session_id": null, "status": "started"}

data: {"task_id": "a88f1ec7-...", "delta": "Quantum ", "text": "Quantum "}

data: {"task_id": "a88f1ec7-...", "delta": "computing adalah ", "text": "Quantum computing adalah "}

data: {"task_id": "a88f1ec7-...", "session_id": "73ec9ead-...", "response": "...", "status": "completed"}

data: [DONE]
```

---

## 🌐 Menghubungkan ke Cloudflare Tunnel (HTTPS Domain Publik)

1. Buat Tunnel di **Cloudflare Zero Trust Dashboard** (`Networks` -> `Tunnels`).
2. Masukkan **Tunnel Token** kamu ke file `.env`:
   ```env
   TUNNEL_TOKEN=eyJhI... (token dari dashboard cloudflare)
   ```
3. Di tab **Public Hostnames** Cloudflare, hubungkan subdomain kamu (contoh `dsapi.domainkamu.com`) ke:
   - **Type**: `HTTP`
   - **URL**: `api-gateway:8000`
4. Jalankan aplikasi:
   ```bash
   sudo docker compose up -d
   ```

---

## 🛠️ Menjalankan & Mengelola Service

```bash
# Menyalakan semua service di background
sudo docker compose up -d

# Memeriksa status kesehatan API
curl http://localhost:8000/health

# Restart worker setelah mengedit prompt/file
sudo docker compose restart worker api-gateway

# Memeriksa log aktivitas worker
sudo docker compose logs worker -f
```
