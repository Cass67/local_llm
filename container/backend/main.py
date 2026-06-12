from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from .config import VERSION
from .routes.models import router as models_router
from .routes.switch import router as switch_router
from .routes.logs import router as logs_router
from .routes.pi import router as pi_router
from .routes.chat import router as chat_router

app = FastAPI(title="local-llm-server", version=VERSION)

app.include_router(models_router)
app.include_router(switch_router)
app.include_router(logs_router)
app.include_router(pi_router)
app.include_router(chat_router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": VERSION}


# SPA fallback: mount UI dist at /ui/
ui_dist = Path(__file__).parent.parent / "ui-dist"
if ui_dist.exists():
    app.mount("/ui", StaticFiles(directory=str(ui_dist), html=True), name="ui")
