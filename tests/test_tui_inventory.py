from __future__ import annotations

from scripts.model_manager.service import inventory_rows_from_stdout
from scripts.model_manager.tui import build_list_rows


def test_inventory_rows_from_stdout_keeps_remote_gemma_12b():
    stdout = (
        '{"repo":"unsloth/gemma-4-12B-it-qat-GGUF",'
        '"path":"/remote/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf",'
        '"file":"gemma-4-12B-it-qat-UD-Q4_K_XL.gguf",'
        '"disk_gb":"6.5","gguf":"yes"}\n'
    )

    rows = inventory_rows_from_stdout(stdout)

    assert rows == [
        {
            "repo": "unsloth/gemma-4-12B-it-qat-GGUF",
            "path": "/remote/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf",
            "file": "gemma-4-12B-it-qat-UD-Q4_K_XL.gguf",
            "disk_gb": "6.5",
            "gguf": "yes",
        }
    ]


def test_build_list_rows_marks_unaccepted_disk_models_disk_only():
    accepted = [
        (
            "gemma-4-31b",
            {
                "repo": "unsloth/gemma-4-31B-it-qat-GGUF",
                "alias": "gemma-4-31b-it-qat-gguf",
                "profile": "balanced",
                "config": {"ctx": 131072},
                "hf_file": "gemma31.gguf",
            },
        )
    ]
    inventory = [
        {"repo": "unsloth/gemma-4-31B-it-qat-GGUF", "file": "gemma31.gguf"},
        {"repo": "unsloth/gemma-4-12B-it-qat-GGUF", "file": "gemma12.gguf"},
    ]

    rows = build_list_rows(accepted, inventory)

    assert [row["source"] for row in rows] == ["accepted", "disk-only"]
    assert rows[1]["family"] == "unsloth/gemma-4-12B-it-qat-GGUF"
    assert rows[1]["alias"] == "not accepted"
