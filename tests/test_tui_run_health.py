from __future__ import annotations

from scripts.model_manager.service import models_response_has_alias


def test_models_response_has_alias_rejects_previous_model():
    payload = '{"data":[{"id":"gemma-4-12b-it-qat-gguf"}]}'

    assert not models_response_has_alias(payload, "gemma-4-31b-it-qat-gguf")


def test_models_response_has_alias_accepts_requested_model():
    payload = '{"data":[{"id":"gemma-4-31b-it-qat-gguf"}]}'

    assert models_response_has_alias(payload, "gemma-4-31b-it-qat-gguf")
