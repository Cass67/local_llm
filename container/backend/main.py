from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from .config import VERSION
from .routes.models import router as models_router

app = FastAPI(title="local-llm-server", version=VERSION)

app.include_router(models_router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": VERSION}


# SPA fallback: mount UI dist at /ui/
ui_dist = Path(__file__).parent.parent / "ui-dist"
if ui_dist.exists():
    app.mount("/ui", StaticFiles(directory=str(ui_dist), html=True), name="ui")
