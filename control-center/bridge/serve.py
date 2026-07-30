from __future__ import annotations

import os

import uvicorn

from app.main import app


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.getenv("OAS_BRIDGE_PORT", "22367")),
        log_level="warning",
    )
