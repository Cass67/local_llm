#!/usr/bin/env bash
# test_oc_local.sh - basic tests for oc-local, profiles.json, and model-manager.
# Run from repo root: bash test_oc_local.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"
OC_LOCAL="$REPO_ROOT/scripts/oc-local"
MODEL_MANAGER="$REPO_ROOT/scripts/model-manager.sh"
PROFILES_JSON="$REPO_ROOT/configs/profiles.json"
PASS=0
FAIL=0

pass() {
  PASS=$((PASS + 1))
  echo "PASS: $*"
}

fail() {
  FAIL=$((FAIL + 1))
  echo "FAIL: $*"
}

# 1. profiles.json exists and is valid JSON
if [[ -f "$PROFILES_JSON" ]]; then
  if jq empty "$PROFILES_JSON" &>/dev/null; then
    pass "profiles.json is valid JSON"
  else
    fail "profiles.json is not valid JSON"
  fi
else
  fail "profiles.json missing"
fi

# 2. All profile keys have required fields
REQUIRED_FIELDS=("family" "model_name" "hf_repo" "quant" "context" "ngl" "batch" "ubatch" "mmproj" "reasoning_effort" "output_limit")
if [[ -f "$PROFILES_JSON" ]]; then
  bad=0
  while IFS= read -r key; do
    for f in "${REQUIRED_FIELDS[@]}"; do
      val="$(jq -r --arg k "$key" --arg f "$f" '.profiles[$k][$f] // empty' "$PROFILES_JSON")"
      if [[ -z "$val" ]]; then
        echo "  Missing field $f in profile $key"
        bad=1
      fi
    done
  done < <(jq -r '.profiles | keys[]' "$PROFILES_JSON")
  if [[ $bad -eq 0 ]]; then
    pass "All profiles have required fields"
  else
    fail "Some profiles missing required fields"
  fi
fi

# 3. All profile families exist in families section
if [[ -f "$PROFILES_JSON" ]]; then
  bad=0
  while IFS= read -r key; do
    fam="$(jq -r --arg k "$key" '.profiles[$k].family' "$PROFILES_JSON")"
    if ! jq -e --arg f "$fam" '.families[$f]' "$PROFILES_JSON" &>/dev/null; then
      echo "  Profile $key references unknown family: $fam"
      bad=1
    fi
  done < <(jq -r '.profiles | keys[]' "$PROFILES_JSON")
  if [[ $bad -eq 0 ]]; then
    pass "All profile families are declared in families section"
  else
    fail "Some profiles reference undeclared families"
  fi
fi

# 4. oc-local list-profiles works
if bash "$OC_LOCAL" list-profiles &>/dev/null; then
  pass "oc-local list-profiles runs without error"
else
  fail "oc-local list-profiles failed"
fi

# 5. oc-local show for a known profile
if bash "$OC_LOCAL" show "qwen:reliable" &>/dev/null; then
  pass "oc-local show qwen:reliable works"
else
  fail "oc-local show qwen:reliable failed"
fi

# 6. oc-local last-runs works (no crash)
if bash "$OC_LOCAL" last-runs 3 &>/dev/null; then
  pass "oc-local last-runs runs without error"
else
  fail "oc-local last-runs failed"
fi

# 7. model-manager status works
if bash "$MODEL_MANAGER" status &>/dev/null; then
  pass "model-manager status runs without error"
else
  fail "model-manager status failed"
fi

# 8. No start*.sh remain
START_SCRIPTS="$(find "$SCRIPT_DIR" -maxdepth 1 -name 'start*.sh' -type f | wc -l | tr -d ' ')"
if [[ "$START_SCRIPTS" -eq 0 ]]; then
  pass "No start*.sh scripts remain"
else
  fail "start*.sh scripts still present"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
