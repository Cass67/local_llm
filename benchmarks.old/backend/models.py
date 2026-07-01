from pydantic import BaseModel


class ModelConfig(BaseModel):
    quant: str | None = None
    batch: int = 4096
    ubatch: int = 256
    ngl: int = 999
    visible_devices: str | None = None
    split_mode: str | None = None
    tensor_split: str | None = None


class ModelInfo(BaseModel):
    family: str
    alias: str
    model_name: str
    label: str | None = None
    profile: str
    context: int | None = None
    backend: str = "rocm"
    reasoning: bool = False
    config: ModelConfig = ModelConfig()
    running: bool = False
    downloaded: bool = True


class ModelListResponse(BaseModel):
    models: list[ModelInfo]
