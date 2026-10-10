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
}

export type ExtractionMode = 'text' | 'table' | 'formula';

export interface EngineSettings {
  status: 'running' | 'offline';
  backend: 'llama-cpp' | 'ollama' | 'vllm';
  runtimeSource: 'managed' | 'custom';
  customLlamaServerPath?: string;
  targetBackend: 'auto' | 'cuda' | 'vulkan' | 'cpu';
  autoStart: boolean;
  renderDpi: number; // 72, 100, 150, 200
  maxImageSize: number;
  maxTokensPerPage: number;
  maxPagesPerDoc: string;
  endpointUrl: string;
  allowRemote: boolean;
  timeout: number;
  retries: number;
  modelRepo: string;
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

