# lib/response.py — Standard JSON response helpers

from fastapi.responses import JSONResponse


def success(data, status: int = 200) -> JSONResponse:
    """200 success wrapper."""
    return JSONResponse(content={"success": True, "data": data}, status_code=status)


def error(message: str, status: int = 400) -> JSONResponse:
    """Error wrapper (400, 401, 403, 429, 500, etc.)."""
    return JSONResponse(content={"success": False, "error": message}, status_code=status)

