# lib/response.py — Standard JSON response helpers

from fastapi.responses import JSONResponse


def success(data, status: int = 200) -> JSONResponse:
    """200 success wrapper."""
    return JSONResponse(content={"success": True, "data": data}, status_code=status)


def error(message: str, status: int = 400, data=None) -> JSONResponse:
    """Error wrapper (400, 401, 403, 429, 500, etc.). Optional data field."""
    body = {"success": False, "error": message}
    if data is not None:
        body["data"] = data
    return JSONResponse(content=body, status_code=status)
