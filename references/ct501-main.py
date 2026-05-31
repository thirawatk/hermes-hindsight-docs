"""Hermes Monitoring Dashboard - FastAPI backend."""
import json
import jinja2
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from services import (
    get_boards, get_tasks,
    get_gateway_status, get_storage, get_hindsight_health, get_bank_stats,
    get_bank_list_with_stats, recall, health as hs_health, version as hs_version,
)

app = FastAPI(title="Hermes Dashboard")
app.mount("/static", StaticFiles(directory="/opt/hermes-dashboard/static"), name="static")

_templates_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader("/opt/hermes-dashboard/templates"),
    cache_size=0,
    auto_reload=True,
)

def render(name: str, ctx: dict) -> str:
    return _templates_env.get_template(name).render(ctx)


# ── Pages (all nav-less, designed for Grafana iframe) ────────────────────────

@app.get("/", response_class=HTMLResponse)
async def overview():
    return HTMLResponse(render("overview.html", {
        "hindsight": get_hindsight_health(),
        "gw": get_gateway_status(),
        "storage": get_storage(),
        "banks": get_bank_stats(),
        "boards": get_boards(),
    }))

@app.get("/hermes", response_class=HTMLResponse)
async def hermes():
    return HTMLResponse(render("hermes.html", {
        "gw": get_gateway_status(),
        "storage": get_storage(),
        "hindsight": get_hindsight_health(),
        "banks": get_bank_stats(),
    }))

@app.get("/hindsight", response_class=HTMLResponse)
async def hindsight():
    return HTMLResponse(render("hindsight.html", {
        "banks": get_bank_list_with_stats(),
        "health": hs_health(),
        "version": hs_version(),
    }))

@app.get("/kanban", response_class=HTMLResponse)
async def kanban():
    return HTMLResponse(render("kanban.html", {
        "boards": get_boards(),
        "current_board": None,
        "tasks": [],
    }))

@app.get("/kanban/{board_slug}", response_class=HTMLResponse)
async def kanban_board(board_slug: str):
    return HTMLResponse(render("kanban.html", {
        "boards": get_boards(),
        "current_board": board_slug,
        "tasks": get_tasks(board_slug),
    }))


# ── API routes (specific first, catch-all LAST) ─────────────────────────────

@app.get("/api/gateway")
async def api_gateway():
    return JSONResponse(get_gateway_status())

@app.get("/api/storage")
async def api_storage():
    return JSONResponse(get_storage())

@app.get("/api/hindsight/health")
async def api_hindsight_health():
    return JSONResponse(get_hindsight_health())

@app.get("/api/hindsight/banks")
async def api_hindsight_banks():
    return JSONResponse(get_bank_list_with_stats())

@app.post("/api/hindsight/recall/{bank_id}")
async def api_recall(bank_id: str, request: Request):
    body = await request.json()
    return JSONResponse(recall(bank_id, body.get("query", ""), body.get("max_tokens", 500)))

@app.get("/api/kanban/boards")
async def api_kanban_boards():
    return JSONResponse(get_boards())

@app.get("/api/kanban/tasks/{board_slug}")
async def api_kanban_tasks(board_slug: str):
    return JSONResponse(get_tasks(board_slug))


# Catch-all MUST be last
@app.get("/api/{path:path}")
async def api_not_found(path: str):
    return JSONResponse({"error": "Not found"}, status_code=404)
