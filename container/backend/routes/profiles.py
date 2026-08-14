"""Profile management — named load configs per model family."""

import asyncio
import json

from fastapi import APIRouter, HTTPException

from .. import active_runners, config
from ..clusters import get_cluster, list_active, list_clusters
from ..gpu_inventory import detect_gpus
from ..profile_lint import estimate_vram_mb, lint_profile
from ..runtime import _model_path

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


def _load() -> dict:
    if not config.PROFILES_CONFIG.exists():
        return {"families": {}}
    try:
        return json.loads(config.PROFILES_CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        return {"families": {}}


def _save(data: dict, label: str = "") -> None:
    config.save_profiles(data, label)


def _snapshot_meta(path) -> dict:
    try:
        data = json.loads(path.read_text())
        fams = data.get("families", {})
        profiles = sum(len(f.get("profiles", {})) for f in fams.values() if isinstance(f, dict))
    except (OSError, json.JSONDecodeError):
        fams, profiles = {}, 0
    snap_id = path.stem
    stamp, _, label = snap_id.partition("_")
    return {
        "id": snap_id,
        "created_at": stamp,
        "label": label,
        "families": len(fams),
        "profiles": profiles,
        "bytes": path.stat().st_size,
    }


def _snapshot_path(snap_id: str):
    path = (config.PROFILE_SNAPSHOTS_DIR / f"{snap_id}.json").resolve()
    if path.parent != config.PROFILE_SNAPSHOTS_DIR.resolve() or not path.exists():
        raise HTTPException(404, f"no such snapshot: {snap_id}")
    return path


@router.get("/snapshots")
async def list_snapshots():
    if not config.PROFILE_SNAPSHOTS_DIR.exists():
        return {"snapshots": []}
    paths = sorted(config.PROFILE_SNAPSHOTS_DIR.glob("*.json"), reverse=True)
    return {"snapshots": [_snapshot_meta(p) for p in paths]}


@router.post("/snapshots")
async def create_snapshot(body: dict | None = None):
    label = (body or {}).get("label", "") or "manual"
    snap_id = config.snapshot_profiles(label)
    if snap_id is None:
        raise HTTPException(404, "no profiles.json to snapshot")
    return {"id": snap_id}


@router.get("/snapshots/{snap_id}")
async def get_snapshot(snap_id: str):
    return json.loads(_snapshot_path(snap_id).read_text())


@router.get("/snapshots/{snap_id}/diff")
async def diff_snapshot(snap_id: str):
    """Per-profile comparison of a snapshot against the live config.

    Only profiles that actually differ are returned — the point is to find the one
    thing that got clobbered, not to scroll 88 identical rows.
    """
    old = json.loads(_snapshot_path(snap_id).read_text()).get("families", {})
    new = _load().get("families", {})
    rows = []
    for family in sorted(set(old) | set(new)):
        old_profiles = old.get(family, {}).get("profiles", {})
        new_profiles = new.get(family, {}).get("profiles", {})
        for name in sorted(set(old_profiles) | set(new_profiles)):
            was, now = old_profiles.get(name), new_profiles.get(name)
            if was == now:
                continue
            if was is None:
                status, keys = "added-since", []
            elif now is None:
                status, keys = "deleted-since", sorted(was)
            else:
                status = "changed"
                keys = sorted(k for k in set(was) | set(now) if was.get(k) != now.get(k))
            rows.append({"family": family, "profile": name, "status": status, "keys": keys})
    return {"id": snap_id, "changes": rows}


@router.post("/snapshots/{snap_id}/restore")
async def restore_snapshot(snap_id: str, body: dict | None = None):
    """Restore a whole snapshot, or one profile from it when family+profile are given."""
    snap = json.loads(_snapshot_path(snap_id).read_text())
    family = (body or {}).get("family")
    profile = (body or {}).get("profile")

    if not family or not profile:
        _save(snap, f"pre-restore-{snap_id[:15]}")
        return {"restored": snap_id, "scope": "all", "families": len(snap.get("families", {}))}

    was = snap.get("families", {}).get(family, {}).get("profiles", {}).get(profile)
    if was is None:
        raise HTTPException(404, f"{family}/{profile} not in snapshot {snap_id}")
    data = _load()
    fam = data.setdefault("families", {}).setdefault(family, {"default": profile, "profiles": {}})
    fam["profiles"][profile] = was
    _save(data, f"restore-{family}-{profile}")
    restarted = await asyncio.to_thread(active_runners.restart_running_for_profile, family, profile)
    return {
        "restored": snap_id,
        "scope": f"{family}/{profile}",
        "restarted_clusters": restarted,
    }


@router.delete("/snapshots/{snap_id}")
async def delete_snapshot(snap_id: str):
    _snapshot_path(snap_id).unlink()


@router.get("")
async def get_profiles():
    return _load()


@router.get("/{family}")
async def get_family_profiles(family: str):
    data = _load()
    return data["families"].get(family, {"default": "", "profiles": {}})


def _resolve_name(fam: dict, name: str) -> str:
    """Map a requested profile name onto the existing key that differs only by case.

    Profile lookups elsewhere (restart_running_for_profile, _apply_profile_config) are
    exact string matches, so a differently-cased save would fork the profile and silently
    strand every later edit. Existing odd-cased names stay addressable; new ones are
    normalised to lowercase so the fork cannot happen again.
    """
    for existing in fam.get("profiles", {}):
        if existing.lower() == name.lower():
            return existing
    return name.strip().lower()


def _model_path_for(family: str) -> str | None:
    path = config.ACCEPTED_DIR / f"{family}.json"
    if not path.exists() or path.is_symlink():
        return None
    try:
        accepted = json.loads(path.read_text())
        return _model_path(accepted, config.MODELS_CACHE_DIR)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _vram_mb_for(cluster_id: str | None, family: str) -> int | None:
    """Total VRAM of the target cluster: the requested one, else wherever family runs."""
    cluster = None
    if cluster_id:
        cluster = get_cluster(cluster_id)
    else:
        running = {str(e.get("cluster_id")): e for e in list_active() if e.get("family") == family}
        for candidate in list_clusters():
            if candidate.id in running:
                cluster = candidate
                break
    if cluster is None:
        return None
    pci_ids = set(cluster.gpu_pci_ids)
    total = sum(g.vram_mb or 0 for g in detect_gpus() if g.pci_id in pci_ids)
    return total or None


def _lint(family: str, profile: dict, cluster_id: str | None = None) -> list[dict]:
    try:
        return lint_profile(
            profile,
            model_path=_model_path_for(family),
            vram_mb=_vram_mb_for(cluster_id, family),
        )
    except Exception:  # noqa: BLE001 — linting must never block a save
        return []


@router.put("/{family}/{name}")
async def upsert_profile(family: str, name: str, body: dict):
    data = _load()
    if family not in data["families"]:
        name = name.strip().lower()
        data["families"][family] = {"default": name, "profiles": {}}
    else:
        name = _resolve_name(data["families"][family], name)
    data["families"][family]["profiles"][name] = body
    _save(data, f"edit-{family}-{name}")
    findings = await asyncio.to_thread(_lint, family, body)
    # Blocking: relaunch + _wait_ready sleep-loops up to 120s per cluster.
    # Run off the event loop so other requests (Architecture tab) aren't frozen.
    restarted = await asyncio.to_thread(active_runners.restart_running_for_profile, family, name)
    return {"status": "saved", "restarted_clusters": restarted, "lint": findings}


@router.get("/{family}/{name}/lint")
async def lint_saved_profile(family: str, name: str, cluster_id: str = ""):
    """Preflight a saved profile — unknown fields, dead knobs, predicted VRAM."""
    fam = _load().get("families", {}).get(family)
    if fam:
        name = _resolve_name(fam, name)
    if not fam or name not in fam.get("profiles", {}):
        raise HTTPException(status_code=404, detail="profile not found")
    profile = fam["profiles"][name]
    findings = await asyncio.to_thread(_lint, family, profile, cluster_id or None)
    model_path = _model_path_for(family)
    estimate = estimate_vram_mb(profile, model_path) if model_path else None
    return {
        "lint": findings,
        "vram_estimate": estimate,
        "vram_available_mb": _vram_mb_for(cluster_id or None, family),
    }


@router.delete("/{family}/{name}")
async def delete_profile(family: str, name: str):
    data = _load()
    fam = data.get("families", {}).get(family)
    if fam:
        name = _resolve_name(fam, name)
    if not fam or name not in fam["profiles"]:
        raise HTTPException(status_code=404, detail="profile not found")
    del fam["profiles"][name]
    if fam["default"] == name:
        remaining = list(fam["profiles"])
        fam["default"] = remaining[0] if remaining else ""
    _save(data, f"delete-{family}-{name}")
    return {"status": "deleted"}


@router.post("/{family}/{name}/clone")
async def clone_profile(family: str, name: str, body: dict):
    new_name = body.get("new_name", "").strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="new_name required")
    data = _load()
    fam = data.get("families", {}).get(family)
    if fam:
        name = _resolve_name(fam, name)
    if not fam or name not in fam["profiles"]:
        raise HTTPException(status_code=404, detail="profile not found")
    new_name = _resolve_name(fam, new_name)
    fam["profiles"][new_name] = dict(fam["profiles"][name])
    _save(data, f"clone-{family}-{name}")
    return {"status": "cloned", "name": new_name}


_MODEL_IDENTITY_KEYS = {"backend", "quant"}


# flag → (profile field, value caster), for flags that take a numeric argument
_NUMERIC_FLAGS: dict[str, tuple[str, type]] = {
    "--parallel": ("parallel", int),
    "--cache-ram": ("cache_ram", int),
    "--spec-draft-n-max": ("mtp_draft_n_max", int),
    "--spec-draft-n-min": ("mtp_draft_n_min", int),
    "--spec-draft-p-min": ("mtp_draft_p_min", float),
    "--spec-ngram-mod-n-match": ("ngram_mod_n_match", int),
    "--spec-ngram-mod-n-min": ("ngram_mod_n_min", int),
    "--spec-ngram-mod-n-max": ("ngram_mod_n_max", int),
}


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
        elif tok == "--spec-type" and nxt and not nxt.startswith("-"):
            profile["spec_type"] = nxt
            if any(t.startswith("draft-") for t in nxt.split(",")):
                profile["mtp_enabled"] = True
            i += 2
        elif tok in _NUMERIC_FLAGS and nxt is not None:
            field, cast = _NUMERIC_FLAGS[tok]
            profile.setdefault(field, cast(nxt))
            i += 2
        else:
            remaining.append(tok)
            i += 1
    if remaining:
        profile["flags"] = " ".join(remaining)
    else:
        profile.pop("flags", None)
    return profile


_RUNTIME_DEFAULTS = {
    "cache_prompt": True,
    "cache_ram": 16384,
    "context_shift": True,
    "ctx_checkpoints": 64,
    "checkpoint_min_step": 4096,
    "timeout": 600,
    "threads_http": 2,
    "parallel": 1,
    "no_cont_batching": True,
    "prio": 2,
    "no_warmup": True,
}


def _profile_from_model(model: dict) -> dict:
    """Build a self-contained profile dict from an accepted model's full config."""
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

    # Flatten nested mtp block if present
    if "mtp" in profile and isinstance(profile["mtp"], dict):
        mtp = profile.pop("mtp")
        profile.setdefault("mtp_enabled", bool(mtp.get("enabled")))
        for k in ("draft_n_max", "draft_n_min", "draft_p_min"):
            if mtp.get(k) is not None:
                profile.setdefault(f"mtp_{k}", mtp[k])

    # Promote known raw flags to proper fields
    _extract_flags(profile)

    # Fill in runtime defaults so the profile is fully self-contained
    for field, value in _RUNTIME_DEFAULTS.items():
        profile.setdefault(field, value)

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
        profile = _profile_from_model(model)

        fam = data["families"].setdefault(family, {"default": profile_name, "profiles": {}})
        fam["profiles"][profile_name] = profile  # always overwrite
        imported += 1

    _save(data, "import-from-models")
    return {"imported": imported}


@router.put("/{family}/default/{name}")
async def set_default(family: str, name: str):
    data = _load()
    fam = data.get("families", {}).get(family)
    if not fam:
        raise HTTPException(status_code=404, detail="family not found")
    name = _resolve_name(fam, name)
    if name not in fam["profiles"]:
        raise HTTPException(status_code=404, detail="profile not found")
    fam["default"] = name
    _save(data, f"default-{family}-{name}")
    return {"status": "updated"}
