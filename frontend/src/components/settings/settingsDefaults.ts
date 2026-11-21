import { BackendSettings, EngineSettings } from '../../types';

export const DEFAULT_SETTINGS: BackendSettings = {
  backend: 'llama-cpp',
  local_endpoint: 'http://127.0.0.1:8080/v1',
  runtime_mode: 'managed',
  managed_backend_override: 'auto',
  dpi: 100,
  max_image_dimension: 2048,
  max_tokens: 4096,
  timeout: 60,
  max_retries: 2,
  auto_start_server: false,
  model_repo: 'PaddlePaddle/PaddleOCR-VL-1.6-GGUF',
  allow_remote: false,
  llama_server_path: null,
};

export const MUTABLE_KEYS = [
  'dpi', 'max_image_dimension', 'max_tokens', 'timeout', 'max_retries',
  'auto_start_server', 'backend', 'runtime_mode', 'managed_backend_override',
  'llama_server_path', 'local_endpoint', 'allow_remote', 'model_repo',
] as const;

export function buildInitialFormData(settings?: EngineSettings): BackendSettings {
  return {
    ...DEFAULT_SETTINGS,
    ...(settings?.dpi !== undefined || settings?.renderDpi !== undefined ? { dpi: (settings?.dpi ?? settings?.renderDpi)! } : {}),
    ...(settings?.max_image_dimension !== undefined || settings?.maxImageSize !== undefined ? { max_image_dimension: (settings?.max_image_dimension ?? settings?.maxImageSize)! } : {}),
    ...(settings?.max_tokens !== undefined || settings?.maxTokensPerPage !== undefined ? { max_tokens: (settings?.max_tokens ?? settings?.maxTokensPerPage)! } : {}),
    ...(settings?.timeout !== undefined ? { timeout: settings.timeout } : {}),
    ...(settings?.max_retries !== undefined ? { max_retries: settings.max_retries } : {}),
    ...(settings?.auto_start_server !== undefined ? { auto_start_server: settings.auto_start_server } : {}),
    ...(settings?.backend ? { backend: settings.backend } : {}),
    ...(settings?.local_endpoint ? { local_endpoint: settings.local_endpoint } : {}),
    ...(settings?.runtime_mode ? { runtime_mode: settings.runtime_mode } : {}),
    ...(settings?.managed_backend_override !== undefined ? { managed_backend_override: settings.managed_backend_override } : {}),
    ...(settings?.model_repo ? { model_repo: settings.model_repo } : {}),
    ...(settings?.llama_server_path ? { llama_server_path: settings.llama_server_path } : {}),
    ...(settings?.allow_remote !== undefined ? { allow_remote: settings.allow_remote } : {}),
  };
}
