"""Profile management — named load configs per model family."""

import json

from fastapi import APIRouter, HTTPException

from .. import config

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


def _load() -> dict:
    if not config.PROFILES_CONFIG.exists():
        return {"families": {}}
    try:
        return json.loads(config.PROFILES_CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        return {"families": {}}


def _save(data: dict) -> None:
    config.PROFILES_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    config.PROFILES_CONFIG.write_text(json.dumps(data, indent=2))


@router.get("")
async def get_profiles():
    return _load()


@router.get("/{family}")
async def get_family_profiles(family: str):
    data = _load()
    return data["families"].get(family, {"default": "", "profiles": {}})


@router.put("/{family}/{name}")
async def upsert_profile(family: str, name: str, body: dict):
    data = _load()
    if family not in data["families"]:
        data["families"][family] = {"default": name, "profiles": {}}
    data["families"][family]["profiles"][name] = body
    _save(data)
    return {"status": "saved"}


@router.delete("/{family}/{name}")
async def delete_profile(family: str, name: str):
    data = _load()
    fam = data.get("families", {}).get(family)
    if not fam or name not in fam["profiles"]:
        raise HTTPException(status_code=404, detail="profile not found")
    del fam["profiles"][name]
    if fam["default"] == name:
        remaining = list(fam["profiles"])
        fam["default"] = remaining[0] if remaining else ""
    _save(data)
    return {"status": "deleted"}


@router.post("/{family}/{name}/clone")
async def clone_profile(family: str, name: str, body: dict):
    new_name = body.get("new_name", "").strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="new_name required")
    data = _load()
    fam = data.get("families", {}).get(family)
    if not fam or name not in fam["profiles"]:
        raise HTTPException(status_code=404, detail="profile not found")
    fam["profiles"][new_name] = dict(fam["profiles"][name])
    _save(data)
    return {"status": "cloned", "name": new_name}


_MODEL_IDENTITY_KEYS = {"backend", "quant"}


def _extract_flags(profile: dict) -> dict:
    """Promote known raw flags to structured fields, leave unknown ones in flags."""
    raw = str(profile.get("flags", "")).split()
    remaining: list[str] = []
    i = 0
    while i < len(raw):
        tok = raw[i]
        nxt = raw[i + 1] if i + 1 < len(raw) else None
        if tok in ("-fa", "--flash-attn"):
            profile["flash_attention"] = nxt != "off"
            i += 2 if nxt in ("on", "off") else 1
        elif tok == "--jinja":
            profile["jinja"] = True
            i += 1
        elif tok == "--parallel" and nxt is not None:
            profile.setdefault("parallel", int(nxt))
            i += 2
        elif tok == "--cache-ram" and nxt is not None:
            profile.setdefault("cache_ram", int(nxt))
            i += 2
        elif tok in (
            "--spec-type",
            "--spec-draft-n-max",
            "--spec-draft-n-min",
            "--spec-draft-p-min",
        ):
            i += 2 if nxt and not nxt.startswith("-") else 1
        else:
            remaining.append(tok)
            i += 1
    if remaining:
        profile["flags"] = " ".join(remaining)
    else:
        profile.pop("flags", None)
    return profile


@router.post("/import")
async def import_from_models():
    """Seed profiles from each accepted model's full config. Always overwrites."""
    if not config.ACCEPTED_DIR.exists():
        return {"imported": 0}

    data = _load()
    imported = 0

    for path in sorted(config.ACCEPTED_DIR.glob("*.json")):
        if path.name == "default.json" or path.is_symlink():
            continue
        try:
            model = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(model, dict):
            continue

        family = str(model.get("family", path.stem))
        profile_name = str(model.get("profile", "default"))
        cfg = model.get("config") or {}

        # Copy everything except model-identity fields
        profile: dict = {k: v for k, v in cfg.items() if k not in _MODEL_IDENTITY_KEYS}

        # Normalise ctx → context so the profile JSON is readable
        if "ctx" in profile:
            profile["context"] = profile.pop("ctx")
        elif model.get("context"):
            profile.setdefault("context", model["context"])

        # Top-level reasoning flag (may not be in config block)
        if "reasoning" not in profile and model.get("reasoning") is not None:
            profile["reasoning"] = model["reasoning"]

        # Promote known raw flags to proper fields
        _extract_flags(profile)

        fam = data["families"].setdefault(family, {"default": profile_name, "profiles": {}})
        fam["profiles"][profile_name] = profile  # always overwrite
        imported += 1

    _save(data)
    return {"imported": imported}


@router.put("/{family}/default/{name}")
async def set_default(family: str, name: str):
    data = _load()
    fam = data.get("families", {}).get(family)
    if not fam:
        raise HTTPException(status_code=404, detail="family not found")
    if name not in fam["profiles"]:
        raise HTTPException(status_code=404, detail="profile not found")
    fam["default"] = name
    _save(data)
    return {"status": "updated"}
