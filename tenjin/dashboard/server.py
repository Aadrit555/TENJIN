"""TENJIN Dashboard HTTP Server.

Serves the operational web console and REST API on localhost.
"""

from __future__ import annotations

import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from tenjin.dashboard.api import router as api_router

logger = logging.getLogger("tenjin.dashboard.server")

app = FastAPI(
    title="TENJIN // Autonomous Engineering Console",
    description="Operational console for persistent autonomous personal software-engineering system",
    version="0.1.0",
)

app.include_router(api_router)


@app.get("/", response_class=HTMLResponse)
def serve_index() -> HTMLResponse:
    """Serve the single-page operational engineering dashboard."""
    index_file = Path(__file__).parent / "static" / "index.html"
    if index_file.is_file():
        content = index_file.read_text(encoding="utf-8")
        return HTMLResponse(content=content)
    return HTMLResponse("<h3>TENJIN Dashboard: static/index.html missing</h3>", status_code=500)


def start_dashboard(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Launch the dashboard web server."""
    logger.info("Starting TENJIN Operational Dashboard at http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="warning")
