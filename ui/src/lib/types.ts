export interface ModelConfig {
  quant?: string;
  batch: number;
  ubatch: number;
  ngl: number;
  visible_devices?: string;
  split_mode?: string;
  tensor_split?: string;
}

export interface ModelInfo {
  family: string;
  alias: string;
  model_name: string;
  profile: string;
  context?: number;
  backend: 'rocm' | 'vulkan';
  reasoning: boolean;
  config: ModelConfig;
  launcher_file?: string;
  running: boolean;
}

export interface ModelListResponse {
  models: ModelInfo[];
}

export interface CurrentModelResponse {
  family: string;
  profile: string;
  alias: string;
  backend: string;
  running: boolean;
  llama_server: { status: string };
}

export interface SwitchRequest {
  family: string;
  profile: string;
  backend?: 'rocm' | 'vulkan';
}

export interface SwitchResponse {
  status: string;
  family: string;
  profile: string;
  alias: string;
  backend: string;
}
