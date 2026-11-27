# lib/gemini.py — Gemini AI client and prompt templates

import json
import os
import re
from google import genai


class GeminiQuotaError(Exception):
    """Raised when Gemini returns a 429 / quota error."""
    pass


class GeminiError(Exception):
    """Raised for other Gemini failures."""
    pass


def _get_client() -> genai.Client:
    """Create a Gemini client using GEMINI_API_KEY."""
    return genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))


def _get_model_name() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")


def _strip_code_fences(text: str) -> str:
    """Remove ```lang ... ``` wrappers if present."""
    cleaned = re.sub(r"^```[\w]*\n?", "", text, flags=re.MULTILINE)
    cleaned = re.sub(r"```$", "", cleaned, flags=re.MULTILINE)
    return cleaned.strip()


def _call_gemini(prompt: str) -> str:
    """Call Gemini with quota / error handling. Returns response text."""
    try:
        client = _get_client()
        response = client.models.generate_content(
            model=_get_model_name(),
            contents=prompt,
        )
        return response.text or ""
    except Exception as err:
        msg = str(err).lower()
        # Detect quota / rate-limit errors from Gemini
        if "429" in msg or "quota" in msg or "rate" in msg:
            raise GeminiQuotaError("AI quota exceeded. Please try again later.")
        raise GeminiError(f"AI service error: {type(err).__name__}")


def generate_model_code(json_string: str, language: str) -> str:
    """Generate model/class code from JSON for the given language."""
    prompt = (
        f"You are a code generator. Given the following JSON data, generate a {language} "
        "model/class that represents its structure. Include type annotations where the "
        "language supports them. Return ONLY the code — no explanations, no markdown "
        f"fences, no backticks. Just raw code.\n\nJSON:\n{json_string}"
    )
    return _strip_code_fences(_call_gemini(prompt))


def explain_json_error(json_string: str) -> str:
    """Explain a JSON parsing error in simple English and suggest a fix."""
    prompt = (
        "The following string is invalid JSON. Explain what is wrong in simple, "
        "beginner-friendly English (2-3 sentences). Then provide the corrected JSON. "
        "Format your response exactly like this:\n\n"
        "Explanation: <your explanation>\n\n"
        "Fixed JSON:\n<corrected json>\n\n"
        f"Invalid JSON:\n{json_string}"
    )
    return _call_gemini(prompt)


def fix_json(json_string: str) -> str:
    """
    Ask Gemini to fix invalid JSON. Returns pretty-printed valid JSON.
    Raises ValueError if the AI output is still not valid JSON.
    """
    prompt = (
        "Fix this invalid JSON. Return only the corrected valid JSON, "
        "no explanation, no markdown fences.\n\n"
        f"{json_string}"
    )
    raw = _strip_code_fences(_call_gemini(prompt))
    # Validate the fix
    parsed = json.loads(raw)  # raises ValueError if still bad
    return json.dumps(parsed, indent=2)


def generate_sample_data(description: str) -> str:
    """
    Generate realistic mock JSON for the given description.
    Returns pretty-printed valid JSON.
    Raises ValueError if the AI output is not valid JSON.
    """
    prompt = (
        "Generate realistic mock JSON data for this description. "
        "Return ONLY valid JSON, no explanations, no markdown fences.\n\n"
        f"Description: {description}"
    )
    raw = _strip_code_fences(_call_gemini(prompt))
    parsed = json.loads(raw)  # raises ValueError if bad
    return json.dumps(parsed, indent=2)
