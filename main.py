# main.py — FastAPI application for JSON Validator & Model Code Generator

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from jsonschema import Draft7Validator

from lib.auth import get_api_key, is_valid_key
from lib.gemini import explain_json_error, generate_model_code
from lib.rate_limit import check_rate_limit
from lib.response import error, success
from lib.webhook import deliver_webhook, is_safe_url

# Load .env.local for local development (Vercel injects env vars directly)
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env.local")

SUPPORTED_LANGUAGES = ("typescript", "python", "java", "csharp", "go")
PUBLIC_PATHS = ("/api/openapi",)
MAX_BODY_BYTES = 100 * 1024  # 100 KB

# Disable FastAPI's built-in /docs so we can serve our custom Swagger UI & openapi.json
app = FastAPI(
    title="JSON Validator & Model Code Generator",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# --- Middleware: API key auth + 100 KB size guard on /api/* ---
@app.middleware("http")
async def api_protection_middleware(request: Request, call_next):
    pathname = request.url.path

    # Only protect /api/* routes
    if not pathname.startswith("/api"):
        return await call_next(request)

    # Allow public endpoints
    if pathname in PUBLIC_PATHS and request.method == "GET":
        return await call_next(request)

    # API key check
    api_key = get_api_key(request)
    if not api_key:
        return error("API key missing", 401)

    if not is_valid_key(api_key):
        return error("Invalid API key", 403)

    # Input size guard (100 KB)
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_BYTES:
        return error("Request body too large (max 100 KB)", 413)

    return await call_next(request)


# --- Frontend Pages ---
@app.get("/", response_class=HTMLResponse)
async def home_page():
    html = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    ui_key = os.environ.get("UI_API_KEY", "")
    # Inject UI_API_KEY safely as a JSON string
    return HTMLResponse(content=html.replace("__UI_API_KEY__", json.dumps(ui_key)))


@app.get("/docs", response_class=HTMLResponse)
async def docs_page():
    return FileResponse(BASE_DIR / "static" / "docs.html", media_type="text/html")


# --- API Endpoints ---
@app.post("/api/validate")
async def validate_json(request: Request):
    api_key = get_api_key(request)
    limit = check_rate_limit(api_key)
    if not limit["allowed"]:
        return error("Rate limit exceeded. Try again in 1 minute.", 429)

    try:
        body = await request.json()
        json_str = body.get("json")
        schema = body.get("schema")

        if not json_str or not isinstance(json_str, str):
            return error("Missing or invalid 'json' field. Must be a string.")

        # Try parsing the JSON string
        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError as parse_err:
            return error(f"Invalid JSON: {parse_err.msg} (line {parse_err.lineno}, col {parse_err.colno})")

        # If a JSON schema is provided, validate with jsonschema
        if schema is not None:
            validator = Draft7Validator(schema)
            errors_list = [
                {"message": e.message, "path": list(e.path)}
                for e in validator.iter_errors(parsed)
            ]
            valid = len(errors_list) == 0
            return success({"valid": valid, "errors": None if valid else errors_list})

        return success({"valid": True, "errors": None})
    except Exception as err:
        return error(f"Server error: {err}", 500)


@app.post("/api/generate")
async def generate_code(request: Request):
    api_key = get_api_key(request)
    limit = check_rate_limit(api_key)
    if not limit["allowed"]:
        return error("Rate limit exceeded. Try again in 1 minute.", 429)

    try:
        body = await request.json()
        json_str = body.get("json")
        language = body.get("language")
        webhook_url = body.get("webhook_url")

        if not json_str or not isinstance(json_str, str):
            return error("Missing or invalid 'json' field. Must be a string.")

        if not language or language not in SUPPORTED_LANGUAGES:
            return error(f"Invalid language. Choose one of: {', '.join(SUPPORTED_LANGUAGES)}")

        # Make sure the JSON is valid before calling Gemini
        try:
            json.loads(json_str)
        except json.JSONDecodeError as parse_err:
            return error(f"Invalid JSON: {parse_err.msg} (line {parse_err.lineno}, col {parse_err.colno})")

        if webhook_url and not is_safe_url(webhook_url):
            return error("Invalid webhook URL. Must be a public http(s) URL (no localhost or private IPs).")

        # Generate code with Gemini
        code = generate_model_code(json_str, language)
        gen_id = str(uuid.uuid4())

        # Webhook delivery
        webhook_result = {"delivered": False, "status": None}
        if webhook_url:
            event = {
                "event": "generation.completed",
                "id": gen_id,
                "language": language,
                "status": "success",
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            webhook_result = await deliver_webhook(webhook_url, event)

        return success({
            "id": gen_id,
            "language": language,
            "code": code,
            "webhook": {
                "delivered": webhook_result["delivered"],
                "status": webhook_result["status"],
            },
        })
    except Exception as err:
        return error(f"Server error: {err}", 500)


@app.post("/api/explain-error")
async def explain_error_route(request: Request):
    api_key = get_api_key(request)
    limit = check_rate_limit(api_key)
    if not limit["allowed"]:
        return error("Rate limit exceeded. Try again in 1 minute.", 429)

    try:
        body = await request.json()
        json_str = body.get("json")

        if not json_str or not isinstance(json_str, str):
            return error("Missing or invalid 'json' field. Must be a string.")

        # Check that it IS actually invalid JSON
        try:
            json.loads(json_str)
            return success({
                "explanation": "This JSON is already valid! No errors found.",
                "fixed_json": json_str,
            })
        except json.JSONDecodeError:
            pass

        explanation = explain_json_error(json_str)
        return success({"explanation": explanation})
    except Exception as err:
        return error(f"Server error: {err}", 500)


@app.post("/api/webhook/test")
async def test_webhook(request: Request):
    api_key = get_api_key(request)
    limit = check_rate_limit(api_key)
    if not limit["allowed"]:
        return error("Rate limit exceeded. Try again in 1 minute.", 429)

    try:
        body = await request.json()
        webhook_url = body.get("webhook_url")

        if not webhook_url or not isinstance(webhook_url, str):
            return error("Missing or invalid 'webhook_url' field.")

        if not is_safe_url(webhook_url):
            return error("Invalid webhook URL. Must be a public http(s) URL (no localhost or private IPs).")

        test_event = {
            "event": "webhook.test",
            "id": str(uuid.uuid4()),
            "language": "typescript",
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        result = await deliver_webhook(webhook_url, test_event)
        return success({
            "test": True,
            "webhook_url": webhook_url,
            "delivered": result["delivered"],
            "status": result["status"],
            "error": result.get("error"),
        })
    except Exception as err:
        return error(f"Server error: {err}", 500)


@app.get("/api/openapi")
async def get_openapi():
    try:
        for spec_path in (BASE_DIR / "public" / "openapi.json", BASE_DIR / "static" / "openapi.json"):
            if spec_path.exists():
                spec = spec_path.read_text(encoding="utf-8")
                return Response(content=spec, media_type="application/json", status_code=200)
        return error("OpenAPI spec file not found", 500)
    except Exception:
        return error("Could not load OpenAPI spec", 500)

