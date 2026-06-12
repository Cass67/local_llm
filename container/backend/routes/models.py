"""Model listing endpoint."""
import json
from fastapi import APIRouter
from .. import config
from ..models import ModelInfo, ModelConfig, ModelListResponse

router = APIRouter(prefix="/api", tags=["models"])


def _read_accepted_models() -> list[ModelInfo]:
    models: list[ModelInfo] = []
    if not config.ACCEPTED_DIR.exists():
        return models

    for path in sorted(config.ACCEPTED_DIR.glob("*.json")):
        if path.name == "default.json":
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue

        family = data.get("family", path.stem)
        alias = data.get("alias", data.get("model_name", family))
        config_data = data.get("config") or {}
        model_cfg = ModelConfig(
            quant=config_data.get("quant"),
            batch=config_data.get("batch", 4096),
            ubatch=config_data.get("ubatch", 256),
            ngl=config_data.get("ngl", 999),
            visible_devices=config_data.get("visible_devices"),
            split_mode=config_data.get("split_mode"),
            tensor_split=config_data.get("tensor_split"),
        )

        launcher_file = data.get("launcher_file")

        models.append(
            ModelInfo(
                family=str(family),
                alias=str(alias),
                model_name=str(data.get("model_name", family)),
                profile=str(data.get("profile", "reliable")),
                context=data.get("context"),
                backend=str(data.get("backend", "rocm")),
                reasoning=bool(data.get("reasoning", False)),
                config=model_cfg,
                launcher_file=str(launcher_file) if launcher_file else None,
                running=False,
            )
        )
    return models


@router.get("/models", response_model=ModelListResponse)
async def list_models():
    models = _read_accepted_models()
    return ModelListResponse(models=models)
