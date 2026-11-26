# JSON Validator & Model Code Generator

A full-stack **Python (FastAPI)** web app that validates JSON and generates model/class code
using **Gemini AI**. It includes a secured REST API with webhook support,
rate limiting, and interactive Swagger UI documentation.

---

## Features

- **JSON Validation** — Parse JSON and optionally validate against a JSON Schema (`jsonschema`)
- **Model Code Generation** — Generate TypeScript, Python, Java, C#, or Go models from JSON using Gemini AI
- **Error Explanation** — Gemini explains what's wrong with invalid JSON in simple English
- **Webhook Delivery** — HMAC-SHA256-signed webhook events on code generation
- **API Key Auth** — Secure all endpoints with `x-api-key` header
- **Rate Limiting** — 30 requests/minute per key (in-memory)
- **Swagger UI** — Interactive API docs at `/docs`

---

## Tech Stack

| Layer      | Technology                              |
| ---------- | --------------------------------------- |
| Backend    | Python 3 + FastAPI + Uvicorn            |
| AI         | Google Gemini (`google-genai`)          |
| Validation | `jsonschema`                            |
| HTTP Client| `httpx`                                 |
| Frontend   | HTML + Plain CSS + Vanilla JS (`fetch`) |
| Deployment | Vercel (`@vercel/python`)               |

---

## Setup

### 1. Clone & install

```bash
git clone <your-repo-url>
cd json-model-gen
python -m pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env.local
```

Edit `.env.local`:

```env
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-3.5-flash-lite
API_KEYS=my-secret-key-1,my-secret-key-2,demo-ui-key
UI_API_KEY=demo-ui-key
WEBHOOK_SECRET=my-webhook-secret
```

> **Note:** `UI_API_KEY` is injected into the frontend HTML so the browser UI can call the API. This is fine for a college demo; production apps use a server-side session/proxy instead.

### 3. Run locally

```bash
python -m uvicorn main:app --reload --port 3000
```

Open [http://localhost:3000](http://localhost:3000)

---

## Environment Variables

| Variable         | Description                                |
| ---------------- | ------------------------------------------ |
| `GEMINI_API_KEY` | Google Gemini API key                      |
| `GEMINI_MODEL`   | Model name (default: `gemini-3.5-flash-lite`) |
| `API_KEYS`       | Comma-separated list of valid API keys     |
| `UI_API_KEY`     | Key the web UI sends (must be in `API_KEYS`) |
| `WEBHOOK_SECRET` | HMAC-SHA256 signing secret for webhooks    |

---

## API Endpoints

All endpoints return JSON in this format:

```json
// Success
{ "success": true, "data": { ... } }

// Error
{ "success": false, "error": "message" }
```

### Authentication

Send the header `x-api-key: <your-key>` with every request (except `GET /api/openapi`).

---

### POST /api/validate

Validate a JSON string, optionally against a JSON Schema.

```bash
curl -X POST http://localhost:3000/api/validate \
  -H "Content-Type: application/json" \
  -H "x-api-key: my-secret-key-1" \
  -d '{"json": "{\"name\": \"Alice\", \"age\": 30}"}'
```

---

### POST /api/generate

Generate model code from JSON using Gemini AI.

```bash
curl -X POST http://localhost:3000/api/generate \
  -H "Content-Type: application/json" \
  -H "x-api-key: my-secret-key-1" \
  -d '{"json": "{\"name\": \"Alice\", \"age\": 30}", "language": "python"}'
```

---

### POST /api/explain-error

Explain what's wrong with invalid JSON.

```bash
curl -X POST http://localhost:3000/api/explain-error \
  -H "Content-Type: application/json" \
  -H "x-api-key: my-secret-key-1" \
  -d '{"json": "{name: \"Alice\"}"}'
```

---

### POST /api/webhook/test

Test webhook delivery to a URL.

```bash
curl -X POST http://localhost:3000/api/webhook/test \
  -H "Content-Type: application/json" \
  -H "x-api-key: my-secret-key-1" \
  -d '{"webhook_url": "https://webhook.site/your-unique-id"}'
```

---

### GET /api/openapi

Get the OpenAPI spec (no auth required).

```bash
curl http://localhost:3000/api/openapi
```

---

## Webhook Payload

When a code generation request includes `webhook_url`, the server POSTs:

```json
{
  "event": "generation.completed",
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "language": "typescript",
  "status": "success",
  "timestamp": "2025-01-15T10:30:00.000Z"
}
```

**Headers:**
- `Content-Type: application/json`
- `X-Signature: <HMAC-SHA256 hex digest of the body>`

### Verifying the signature (Python example)

```python
import hashlib, hmac

def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
```

---

## Deploy to Vercel

1. Push your code to GitHub
2. Go to [vercel.com](https://vercel.com) → New Project → Import your repo
3. Add all environment variables in **Settings → Environment Variables**:
   - `GEMINI_API_KEY`
   - `GEMINI_MODEL`
   - `API_KEYS`
   - `UI_API_KEY`
   - `WEBHOOK_SECRET`
4. Click **Deploy**

---

## Project Structure

```
json-model-gen/
├── main.py                      # FastAPI app, middleware & routes
├── api/
│   └── index.py                 # Vercel serverless entrypoint
├── lib/
│   ├── __init__.py
│   ├── gemini.py                # Gemini client + prompts
│   ├── auth.py                  # API key helpers
│   ├── rate_limit.py            # In-memory rate limiter
│   ├── webhook.py               # HMAC signing + delivery
│   └── response.py              # JSON response helpers
├── static/
│   ├── index.html               # Frontend UI
│   ├── docs.html                # Swagger UI
│   └── styles.css               # Styling
├── public/openapi.json          # OpenAPI specification
├── requirements.txt             # Python dependencies
├── vercel.json                  # Vercel config
├── .env.example                 # Template env file
└── README.md
```

---

## License

MIT
