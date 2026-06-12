from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from .config import VERSION

app = FastAPI(title="local-llm-server", version=VERSION)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": VERSION}


# SPA fallback: mount UI dist at /ui/
ui_dist = Path(__file__).parent.parent / "ui-dist"
if ui_dist.exists():
    app.mount("/ui", StaticFiles(directory=str(ui_dist), html=True), name="ui")
