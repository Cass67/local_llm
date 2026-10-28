import os
import tempfile
from pathlib import Path

# backend.config reads these at import. Inside the mgmt container /state is live state, so a
# test that forgets a monkeypatch must land in scratch, not in the real profiles or snapshots.
_state = Path(tempfile.mkdtemp(prefix="local-llm-test-state-"))
os.environ["LOCAL_LLM_STATE_DIR"] = str(_state)
os.environ["PROFILES_CONFIG"] = str(_state / "profiles.json")
os.environ["ROUTER_CONFIG"] = str(_state / "router_rules.json")
