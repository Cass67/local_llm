import type { ModelListResponse, CurrentModelResponse, SwitchRequest, SwitchResponse } from './types';

const BASE = '';

export async function fetchModels(): Promise<ModelListResponse> {
  const res = await fetch(`${BASE}/api/models`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function fetchCurrentModel(): Promise<CurrentModelResponse> {
  const res = await fetch(`${BASE}/api/models/current`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function switchModel(req: SwitchRequest): Promise<SwitchResponse> {
  const res = await fetch(`${BASE}/api/models/switch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}
