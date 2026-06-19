import logging

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from importlib import import_module
from . import active_runners
from .config import VERSION
from .routes.models import router as models_router
from .routes.switch import router as switch_router
from .routes.logs import router as logs_router
from .routes.pi import router as pi_router
from .routes.chat import router as chat_router
from .routes.search import router as search_router
from .routes.manage import router as manage_router
from .routes.init import router as init_router
from .routes.openai import router as openai_router
from .routes.stats import router as stats_router
from .routes.runner import router as runner_router
from .routes.clusters import router as clusters_router
from .routes.router_config import router as router_config_router
from .routes.idle_unload import router as idle_unload_router

benchmark_router = import_module("backend.routes.benchmark").router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="local-llm-server", version=VERSION)


@app.on_event("startup")
async def restore_desired_runners():
    import asyncio

    await asyncio.to_thread(active_runners.restore_desired, _resolve_accepted_for_restore)
    asyncio.create_task(_idle_unload_loop())


async def _idle_unload_loop():
    import asyncio
    from .routes.idle_unload import load as _load_idle_cfg

    while True:
        await asyncio.sleep(60)
        cfg = _load_idle_cfg()
        if cfg.get("enabled"):
            timeout_s = float(cfg.get("timeout_minutes", 10)) * 60
            await asyncio.to_thread(active_runners.idle_check, timeout_s)


def _resolve_accepted_for_restore(family: str) -> dict:
    from .routes.clusters import _resolve_accepted

    return _resolve_accepted(family)


@app.middleware("http")
async def local_llm_api_prefix(request, call_next):
    if request.scope.get("path", "").startswith("/api/local-llm/"):
        request.scope["path"] = "/api/" + request.scope["path"].removeprefix("/api/local-llm/")
    return await call_next(request)


app.include_router(models_router)
app.include_router(switch_router)
app.include_router(logs_router)
app.include_router(pi_router)
app.include_router(chat_router)
app.include_router(search_router)
app.include_router(manage_router)
app.include_router(init_router)
app.include_router(openai_router)
app.include_router(stats_router)
app.include_router(runner_router)
app.include_router(clusters_router)
app.include_router(router_config_router)
app.include_router(idle_unload_router)
app.include_router(benchmark_router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": VERSION}


@app.get("/chat/")
@app.get("/chat")
async def chat_redirect(request: Request):
    host = request.url.hostname or "127.0.0.1"
    return RedirectResponse(f"{request.url.scheme}://{host}:3001/chat/")


@app.get("/traces/")
@app.get("/traces")
async def traces_redirect(request: Request):
    host = request.url.hostname or "127.0.0.1"
    return RedirectResponse(f"{request.url.scheme}://{host}:3004/")


# SPA fallback: mount UI dist at /ui/
ui_dist = Path(__file__).parent.parent / "ui-dist"
if ui_dist.exists():
    app.mount("/ui", StaticFiles(directory=str(ui_dist), html=True), name="ui")
