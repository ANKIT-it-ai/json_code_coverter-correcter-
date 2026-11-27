# main.py — FastAPI application for JSON Validator & Model Code Generator

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from jsonschema import Draft7Validator

from lib.auth import get_api_key, is_valid_key
from lib.gemini import (
    GeminiError,
    GeminiQuotaError,
    explain_json_error,
    fix_json,
    generate_model_code,
    generate_sample_data,
)
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
def _render_ui_page(filename: str) -> HTMLResponse:
    """Read a static HTML page and inject UI_API_KEY safely."""
    html = (BASE_DIR / "static" / filename).read_text(encoding="utf-8")
    ui_key = os.environ.get("UI_API_KEY", "")
    return HTMLResponse(content=html.replace("__UI_API_KEY__", json.dumps(ui_key)))


@app.get("/", response_class=HTMLResponse)
async def home_page():
    return _render_ui_page("index.html")


@app.get("/diff", response_class=HTMLResponse)
async def diff_page():
    return _render_ui_page("diff.html")


@app.get("/docs", response_class=HTMLResponse)
async def docs_page():
    return FileResponse(BASE_DIR / "static" / "docs.html", media_type="text/html")


@app.get("/openapi", response_class=HTMLResponse)
async def openapi_page():
    return FileResponse(BASE_DIR / "static" / "openapi.html", media_type="text/html")


# ===================== API ENDPOINTS =====================

# --- POST /api/validate (Feature 3: returns line/column on error) ---
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
            # Feature 3: return line, column, position in data
            err_data = {
                "line": parse_err.lineno,
                "column": parse_err.colno,
                "position": parse_err.pos,
            }
            return error(
                f"Invalid JSON: {parse_err.msg} (line {parse_err.lineno}, col {parse_err.colno})",
                400,
                data=err_data,
            )

        # If a JSON schema is provided, validate with jsonschema
        if schema is not None:
            # Schema must be a dict
            if not isinstance(schema, dict):
                return error("Schema must be a JSON object (not a string).")
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


# --- POST /api/generate ---
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

        try:
            json.loads(json_str)
        except json.JSONDecodeError as parse_err:
            return error(f"Invalid JSON: {parse_err.msg} (line {parse_err.lineno}, col {parse_err.colno})")

        if webhook_url and not is_safe_url(webhook_url):
            return error("Invalid webhook URL. Must be a public http(s) URL (no localhost or private IPs).")

        # Generate code with Gemini (quota-aware)
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
    except GeminiQuotaError:
        return error("AI quota exceeded. Please try again later.", 429)
    except GeminiError as ge:
        return error(str(ge), 500)
    except Exception as err:
        return error(f"Server error: {err}", 500)


# --- POST /api/explain-error ---
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
    except GeminiQuotaError:
        return error("AI quota exceeded. Please try again later.", 429)
    except GeminiError as ge:
        return error(str(ge), 500)
    except Exception as err:
        return error(f"Server error: {err}", 500)


# --- POST /api/webhook/test ---
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


# --- Feature 4: POST /api/fix-json (Auto-fix with Gemini) ---
@app.post("/api/fix-json")
async def fix_json_route(request: Request):
    api_key = get_api_key(request)
    limit = check_rate_limit(api_key)
    if not limit["allowed"]:
        return error("Rate limit exceeded. Try again in 1 minute.", 429)

    try:
        body = await request.json()
        json_str = body.get("json")

        if not json_str or not isinstance(json_str, str):
            return error("Missing or invalid 'json' field. Must be a string.")

        fixed = fix_json(json_str)
        return success({"fixed": fixed})
    except (json.JSONDecodeError, ValueError):
        return error("AI could not produce valid JSON. Try editing manually.", 422)
    except GeminiQuotaError:
        return error("AI quota exceeded. Please try again later.", 429)
    except GeminiError as ge:
        return error(str(ge), 500)
    except Exception as err:
        return error(f"Server error: {err}", 500)


# --- Feature 5: POST /api/diff (JSON diff, no AI) ---
def _deep_diff(left, right, path=""):
    """Recursively compare two parsed JSON values. Returns (added, removed, changed)."""
    added, removed, changed = [], [], []

    if isinstance(left, dict) and isinstance(right, dict):
        all_keys = set(list(left.keys()) + list(right.keys()))
        for key in sorted(all_keys):
            child_path = f"{path}.{key}" if path else key
            if key not in left:
                added.append({"path": child_path, "value": right[key]})
            elif key not in right:
                removed.append({"path": child_path, "value": left[key]})
            else:
                a, r, c = _deep_diff(left[key], right[key], child_path)
                added.extend(a)
                removed.extend(r)
                changed.extend(c)
    elif isinstance(left, list) and isinstance(right, list):
        max_len = max(len(left), len(right))
        for i in range(max_len):
            child_path = f"{path}[{i}]"
            if i >= len(left):
                added.append({"path": child_path, "value": right[i]})
            elif i >= len(right):
                removed.append({"path": child_path, "value": left[i]})
            else:
                a, r, c = _deep_diff(left[i], right[i], child_path)
                added.extend(a)
                removed.extend(r)
                changed.extend(c)
    else:
        if left != right:
            changed.append({"path": path or "(root)", "from": left, "to": right})

    return added, removed, changed


@app.post("/api/diff")
async def diff_json(request: Request):
    api_key = get_api_key(request)
    limit = check_rate_limit(api_key)
    if not limit["allowed"]:
        return error("Rate limit exceeded. Try again in 1 minute.", 429)

    try:
        body = await request.json()
        left_str = body.get("left")
        right_str = body.get("right")

        if not left_str or not isinstance(left_str, str):
            return error("Missing or invalid 'left' field. Must be a JSON string.")
        if not right_str or not isinstance(right_str, str):
            return error("Missing or invalid 'right' field. Must be a JSON string.")

        # Parse left
        try:
            left = json.loads(left_str)
        except json.JSONDecodeError as e:
            return error(f"Left JSON is invalid: {e.msg} (line {e.lineno}, col {e.colno})")

        # Parse right
        try:
            right = json.loads(right_str)
        except json.JSONDecodeError as e:
            return error(f"Right JSON is invalid: {e.msg} (line {e.lineno}, col {e.colno})")

        added, removed, changed = _deep_diff(left, right)
        return success({
            "added": added,
            "removed": removed,
            "changed": changed,
            "identical": len(added) == 0 and len(removed) == 0 and len(changed) == 0,
        })
    except Exception as err:
        return error(f"Server error: {err}", 500)


# --- Feature 6: POST /api/sample (Sample data generator) ---
@app.post("/api/sample")
async def sample_data(request: Request):
    api_key = get_api_key(request)
    limit = check_rate_limit(api_key)
    if not limit["allowed"]:
        return error("Rate limit exceeded. Try again in 1 minute.", 429)

    try:
        body = await request.json()
        description = body.get("description")

        if not description or not isinstance(description, str):
            return error("Missing or invalid 'description' field. Must be a string.")

        if len(description) > 200:
            return error("Description too long. Max 200 characters.")

        sample = generate_sample_data(description)
        return success({"json": sample})
    except (json.JSONDecodeError, ValueError):
        return error("AI could not produce valid JSON. Try a different description.", 422)
    except GeminiQuotaError:
        return error("AI quota exceeded. Please try again later.", 429)
    except GeminiError as ge:
        return error(str(ge), 500)
    except Exception as err:
        return error(f"Server error: {err}", 500)


# --- Feature 7: POST /api/generate/batch (Batch code generation) ---
@app.post("/api/generate/batch")
async def batch_generate(request: Request):
    api_key = get_api_key(request)
    limit = check_rate_limit(api_key)
    if not limit["allowed"]:
        return error("Rate limit exceeded. Try again in 1 minute.", 429)

    try:
        body = await request.json()
        json_str = body.get("json")
        languages = body.get("languages")
        webhook_url = body.get("webhook_url")

        if not json_str or not isinstance(json_str, str):
            return error("Missing or invalid 'json' field. Must be a string.")

        # Validate languages
        if not languages or not isinstance(languages, list) or len(languages) == 0:
            return error("Missing or invalid 'languages' field. Must be a list of 1-5 languages.")

        if len(languages) > 5:
            return error("Too many languages. Max 5 at a time.")

        # Check for duplicates
        if len(set(languages)) != len(languages):
            return error("Duplicate languages are not allowed.")

        # Check for unknown languages
        for lang in languages:
            if lang not in SUPPORTED_LANGUAGES:
                return error(f"Unknown language: '{lang}'. Choose from: {', '.join(SUPPORTED_LANGUAGES)}")

        # Validate JSON once
        try:
            json.loads(json_str)
        except json.JSONDecodeError as parse_err:
            return error(f"Invalid JSON: {parse_err.msg} (line {parse_err.lineno}, col {parse_err.colno})")

        if webhook_url and not is_safe_url(webhook_url):
            return error("Invalid webhook URL. Must be a public http(s) URL (no localhost or private IPs).")

        batch_id = str(uuid.uuid4())

        # Generate code for each language in parallel
        async def gen_one(lang):
            """Run Gemini code generation for one language (runs in thread)."""
            try:
                code = await asyncio.to_thread(generate_model_code, json_str, lang)
                return {"language": lang, "status": "success", "code": code}
            except GeminiQuotaError:
                return {"language": lang, "status": "failed", "error": "AI quota exceeded"}
            except Exception as e:
                return {"language": lang, "status": "failed", "error": str(e)}

        results = await asyncio.gather(*[gen_one(lang) for lang in languages])

        # Webhook delivery (one webhook for the whole batch)
        if webhook_url:
            event = {
                "event": "batch.completed",
                "id": batch_id,
                "results": [
                    {"language": r["language"], "status": r["status"]}
                    for r in results
                ],
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            await deliver_webhook(webhook_url, event)

        return success({"id": batch_id, "results": list(results)})
    except GeminiQuotaError:
        return error("AI quota exceeded. Please try again later.", 429)
    except GeminiError as ge:
        return error(str(ge), 500)
    except Exception as err:
        return error(f"Server error: {err}", 500)


# --- GET /api/openapi ---
@app.get("/api/openapi")
async def get_openapi(request: Request):
    # Redirect direct browser page visits to the styled OpenAPI JSON viewer unless raw=1 is requested.
    accept = request.headers.get("accept", "")
    if request.query_params.get("raw") != "1" and "text/html" in accept:
        return RedirectResponse(url="/openapi", status_code=302)

    try:
        for spec_path in (BASE_DIR / "public" / "openapi.json", BASE_DIR / "static" / "openapi.json"):
            if spec_path.exists():
                spec = spec_path.read_text(encoding="utf-8")
                return Response(content=spec, media_type="application/json", status_code=200)
        return error("OpenAPI spec file not found", 500)
    except Exception:
        return error("Could not load OpenAPI spec", 500)
