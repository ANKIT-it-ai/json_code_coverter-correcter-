# lib/gemini.py — Gemini AI client and prompt templates

import os
import re
from google import genai


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


def generate_model_code(json_string: str, language: str) -> str:
    """
    Generate model/class code from JSON for the given language.
    Returns plain code string (no markdown fences).
    """
    client = _get_client()
    prompt = (
        f"You are a code generator. Given the following JSON data, generate a {language} "
        "model/class that represents its structure. Include type annotations where the "
        "language supports them. Return ONLY the code — no explanations, no markdown "
        f"fences, no backticks. Just raw code.\n\nJSON:\n{json_string}"
    )

    response = client.models.generate_content(
        model=_get_model_name(),
        contents=prompt,
    )
    return _strip_code_fences(response.text or "")


def explain_json_error(json_string: str) -> str:
    """Explain a JSON parsing error in simple English and suggest a fix."""
    client = _get_client()
    prompt = (
        "The following string is invalid JSON. Explain what is wrong in simple, "
        "beginner-friendly English (2-3 sentences). Then provide the corrected JSON. "
        "Format your response exactly like this:\n\n"
        "Explanation: <your explanation>\n\n"
        "Fixed JSON:\n<corrected json>\n\n"
        f"Invalid JSON:\n{json_string}"
    )

    response = client.models.generate_content(
        model=_get_model_name(),
        contents=prompt,
    )
    return response.text or ""

