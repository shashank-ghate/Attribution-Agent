from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config.settings import settings
from app.core.dependencies import get_report_service


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await get_report_service().moengage.browser.close()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Automates MoEngage attribution metrics into campaign workbooks.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.api_prefix)

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
STATIC_INDEX = STATIC_DIR / "index.html"
if (STATIC_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/")
async def root():
    if STATIC_INDEX.exists():
        return FileResponse(STATIC_INDEX)
    return {"name": settings.app_name, "docs": "/docs", "health": "/api/health"}


@app.get("/{path:path}", include_in_schema=False)
async def frontend(path: str):
    """Serve Vite output in production, with an SPA fallback."""
    if path == "api" or path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")
    requested = (STATIC_DIR / path).resolve()
    if STATIC_INDEX.exists() and requested.is_relative_to(STATIC_DIR.resolve()) and requested.is_file():
        return FileResponse(requested)
    if STATIC_INDEX.exists():
        return FileResponse(STATIC_INDEX)
    return {"detail": "Frontend build not found"}
