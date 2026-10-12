export type DocumentStatus = 'Done' | 'Processing' | 'Truncated' | 'Waiting' | 'Failed' | 'Not extracted';

export interface PageExtraction {
  pageNumber: number;
  text: string;
  isTruncated?: boolean;
  table?: string;
  formula?: string;
  latency?: number;
  tokens?: number;
}

export type PromptMode = 'text' | 'table' | 'formula';

export interface DocumentItem {
  id: string;
  name: string;
  pages: number;
  size?: string;
  status: DocumentStatus;
  statusNote?: string;
  queuePosition?: number;
  isReExtractionQueued?: boolean;
  processedPages?: number;
  currentPage: number; // page being viewed in preview
  extractedText: string; // document-level concatenated text
  pagesData?: Record<number, PageExtraction>; // per-page extracted data
  extractedTable?: string;
  extractedFormula?: string;
  promptMode?: PromptMode;
  docType: 'legal-agreement' | 'invoice' | 'historical-paper' | 'financial' | 'custom-image';
  previewImageUrl?: string;
  runId?: string;
}

export type ExtractionMode = 'text' | 'table' | 'formula';

export interface BackendSettings {
  backend: string;
  local_endpoint: string;
  runtime_mode: string;
  managed_backend_override?: string | null;
  dpi: number;
  max_image_dimension: number;
  max_tokens: number;
  timeout: number;
  max_retries: number;
  auto_start_server: boolean;
  model_repo: string;
  allow_remote?: boolean;
  llama_server_path?: string | null;
}

export interface EngineSettings extends Partial<BackendSettings> {
  status: 'running' | 'offline';
  backend: string;
  runtimeSource?: 'managed' | 'custom';
  customLlamaServerPath?: string;
  targetBackend?: 'auto' | 'cuda' | 'vulkan' | 'cpu';
  autoStart?: boolean;
  renderDpi?: number; // 72, 100, 150, 200
  maxImageSize?: number;
  maxTokensPerPage?: number;
  maxPagesPerDoc?: string;
  endpointUrl?: string;
  allowRemote?: boolean;
  timeout?: number;
  retries?: number;
  modelRepo?: string;
  // Backend canonical fields
  dpi?: number;
  max_image_dimension?: number;
  max_tokens?: number;
  max_retries?: number;
  auto_start_server?: boolean;
  local_endpoint?: string;
  runtime_mode?: string;
  managed_backend_override?: string | null;
  model_repo?: string;
}

export interface DoctorCheckItem {
  category: string;
  title: string;
  status: 'PASS' | 'WARN' | 'FAIL' | string;
  details?: string | string[] | null;
  remediation?: string | null;
}

export interface DoctorReport {
  status: string;
  exit_code: number;
  total_checks: number;
  failed_checks: number;
  checks: DoctorCheckItem[];
  text?: string;
}

export type OutputFormatType = 'docx' | 'md' | 'json' | 'both';

export interface ExportedFile {
  id: string;
  filename: string;
  type: 'md' | 'docx' | 'json' | 'both';
  timestamp: string;
  content: string;
  size: string;
  localPath?: string;
}

