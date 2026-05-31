"""FastAPI entrypoint for CD_LAB.

Run with:
    uvicorn backend.main:app --reload --port 8000

Browser:
    http://localhost:8000/        → static/index.html
    http://localhost:8000/health  → libclang status
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .analyzer import libclang_status
from .routes import analyze as analyze_route
from .routes import explain as explain_route
from .routes import graph as graph_route
from .schemas import HealthResponse

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"

app = FastAPI(title="CD_LAB — UB Detector", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(analyze_route.router)
app.include_router(graph_route.router)
app.include_router(explain_route.router)



@app.get("/")
def root() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    loaded, info = libclang_status()
    return HealthResponse(
        status="ok" if loaded else "degraded",
        libclang_loaded=loaded,
        libclang_path=info,
    )
