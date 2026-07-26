"""
Dashboard serving — added to MCP server.
Appended to mcp/server.py via separate route file for clarity.
"""

# This file's content is merged into server.py
# The dashboard route serves the HTML file directly.

from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import os

DASHBOARD_PATH = os.path.join(os.path.dirname(__file__), "..", "dashboard", "index.html")

def add_dashboard_routes(app):
    @app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
    async def serve_dashboard():
        with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
            return f.read()
