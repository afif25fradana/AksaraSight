import React, { useState, useMemo, useRef, useEffect } from 'react';
import { 
  Download, 
  ChevronDown, 
  Check, 
  Copy,
  Ban, 
  ListPlus, 
  ScanText, 
  AlertTriangle, 
  Play, 
  FileText, 
  AlertCircle, 
  Hourglass,
  Layers,
  Code2,
  FileCode,
  Sparkles
} from 'lucide-react';
import { DocumentItem, PromptMode, OutputFormatType } from '../types';

interface ExtractedTextPanelProps {
  document: DocumentItem | null;
  runningJobDocId: string | null;
  isEngineOnline: boolean;
  onStartEngine: () => void;
  onOpenSettings: () => void;
  onTextChange?: (newText: string, pageNumber?: number) => void;
  onExport: (format: OutputFormatType) => void;
  onRunDocumentExtraction: (docId: string) => void;
  onAddToQueue: (docId: string) => void;
  onRemoveFromQueue: (docId: string) => void;
  onCancelExtraction: (docId: string) => void;
  onReExtractDocument: (docId: string) => void;
}

// Engine-supported formats matching core.models.OutputFormat and core/formatter.py
const EXPORT_FORMATS: { ext: OutputFormatType; title: string; desc: string }[] = [
  { ext: 'docx', title: 'DOCX (.docx)', desc: 'Microsoft Word document' },
  { ext: 'md', title: 'Markdown (.md)', desc: 'Markdown text & tables' },
  { ext: 'json', title: 'JSON (.json)', desc: 'Structured metadata, timing & page tokens' },
  { ext: 'both', title: 'Both (.md + .json)', desc: 'Markdown document and JSON side-by-side' },
];

type PreviewTab = 'formatted' | 'raw' | 'json';

// Syntax-highlighted rendering for JSON Tree with Pro Dark tokens
const highlightJson = (json: string): React.ReactNode => {
  if (!json) return null;
  const regex = /("(?:\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}\[\],]|\s+|[^"{}[\],\s:]+/g;
  const nodes: React.ReactNode[] = [];
  let match: RegExpExecArray | null;
  let idx = 0;

  while ((match = regex.exec(json)) !== null) {
    const [token, strWithQuotes, colon] = match;
    if (colon) {
      nodes.push(
        <span key={idx++} className="text-[#14213D] dark:text-[var(--text-1)] font-semibold">
          {strWithQuotes}
        </span>
      );
      nodes.push(
        <span key={idx++} className="text-[#5A6478] dark:text-[var(--text-3)]">
          {colon}
        </span>
      );
    } else if (token.startsWith('"')) {
      nodes.push(
        <span key={idx++} className="text-[#0F766E] dark:text-[var(--accent)]">
          {token}
        </span>
      );
    } else if (/^(true|false|null)$/.test(token)) {
      nodes.push(
        <span key={idx++} className="text-[#B45309] dark:text-[var(--warning)]">
          {token}
        </span>
      );
    } else if (/^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(token)) {
      nodes.push(
        <span key={idx++} className="text-[#B45309] dark:text-[var(--warning)]">
          {token}
        </span>
      );
    } else if (/^[{}\[\],]$/.test(token)) {
      nodes.push(
        <span key={idx++} className="text-[#5A6478] dark:text-[var(--text-3)]">
          {token}
        </span>
      );
    } else {
      nodes.push(token);
    }
  }
  return nodes;
};

export const ExtractedTextPanel: React.FC<ExtractedTextPanelProps> = ({
  document,
  runningJobDocId,
  isEngineOnline,
  onStartEngine,
  onOpenSettings,
  onExport,
  onRunDocumentExtraction,
  onAddToQueue,
  onRemoveFromQueue,
  onCancelExtraction,
  onReExtractDocument,
}) => {
  const [exportFormat, setExportFormat] = useState<OutputFormatType>('docx');
  const [showExportMenu, setShowExportMenu] = useState<boolean>(false);
  const [copied, setCopied] = useState<boolean>(false);
  const [taskMode, setTaskMode] = useState<PromptMode>('text');
  const [showTaskModeMenu, setShowTaskModeMenu] = useState<boolean>(false);
  const [activePreviewTab, setActivePreviewTab] = useState<PreviewTab>('formatted');
  const [indicatorStyle, setIndicatorStyle] = useState<{ left: number; width: number }>({ left: 2, width: 0 });
  const tabContainerRef = useRef<HTMLDivElement>(null);
  const tabRefs = useRef<{ [key in PreviewTab]?: HTMLButtonElement | null }>({});

  useEffect(() => {
    const updateIndicator = () => {
      const container = tabContainerRef.current;
      const activeEl = tabRefs.current[activePreviewTab];
      if (container && activeEl) {
        const containerRect = container.getBoundingClientRect();
        const tabRect = activeEl.getBoundingClientRect();
        setIndicatorStyle({
          left: tabRect.left - containerRect.left,
          width: tabRect.width,
        });
      }
    };
    updateIndicator();
    window.addEventListener('resize', updateIndicator);
    return () => window.removeEventListener('resize', updateIndicator);
  }, [activePreviewTab]);

  const taskModes = useMemo(() => [
    { mode: 'text' as const, label: 'Text Recognition', desc: 'Standard full-page OCR extraction' },
    { mode: 'table' as const, label: 'Table Recognition', desc: 'Extract tables to GitHub-flavored Markdown' },
    { mode: 'formula' as const, label: 'Formula Recognition', desc: 'Extract mathematical equations to LaTeX' },
  ], []);

  const isEmptyState = !document;
  const isDocOwnerOfRunningJob = Boolean(document && runningJobDocId === document.id);
  const isAnotherJobRunning = Boolean(runningJobDocId && document && runningJobDocId !== document.id);

  const isDoneOrTruncated = Boolean(
    isEngineOnline &&
    document &&
    !isDocOwnerOfRunningJob &&
    (document.status === 'Done' || document.status === 'Truncated') &&
    document.extractedText &&
    document.extractedText.trim().length > 0
  );

  const currentPage = document?.currentPage || 1;
  const processedPages = document?.processedPages || 0;
  const isCurrentPageViewedProcessed = Boolean(
    document &&
    (document.status === 'Done' || document.status === 'Truncated' || currentPage <= processedPages)
  );

  const currentPageData = document?.pagesData?.[currentPage];
  const isCurrentPageTruncated = Boolean(currentPageData?.isTruncated);

  // Content resolved based on taskMode
  const currentTextContent = useMemo(() => {
    if (!document) return '';
    if (taskMode === 'table') {
      return currentPageData?.table || document.extractedTable || document.extractedText || '';
    }
    if (taskMode === 'formula') {
      return currentPageData?.formula || document.extractedFormula || document.extractedText || '';
    }
    return currentPageData?.text || document.extractedText || '';
  }, [document, currentPageData, taskMode]);

  // Structured JSON representation matching core.models.OCRResult.to_dict()
  const structuredJson = useMemo(() => {
    if (!document) return null;
    const isDone = document.status === 'Done';
    const isTrunc = document.status === 'Truncated';
    const pagesList = Array.from({ length: document.pages }, (_, i) => {
      const pageNum = i + 1;
      const pageData = document.pagesData?.[pageNum];
      const isProcessed = isDone || isTrunc || pageNum <= (document.processedPages || 0);
      return {
        page_num: pageNum,
        status: isProcessed ? (pageData?.isTruncated ? 'PARTIAL' : 'SUCCESS') : 'WAITING',
        latency: isProcessed ? +(0.85 + pageNum * 0.28).toFixed(2) : 0.0,
        tokens: isProcessed ? (pageData?.isTruncated ? 4096 : 380 + pageNum * 42) : 0,
        markdown: isProcessed
          ? pageData?.text || (pageNum === 1 ? document.extractedText : `[Page ${pageNum} extracted content]`)
          : '',
        error: null,
        raw_json: isProcessed
          ? {
              model: 'glm-ocr-q4_k_m',
              task: taskMode,
              finish_reason: pageData?.isTruncated ? 'length' : 'stop',
            }
          : null,
        truncated: Boolean(pageData?.isTruncated),
      };
    });

    return {
      file_path: `C:\\Users\\Fradana\\Documents\\AksaraSight\\input\\${document.name}`,
      status: isDone ? 'SUCCESS' : isTrunc ? 'PARTIAL' : document.status === 'Failed' ? 'FAILED' : 'PROCESSING',
      total_duration: +(
        pagesList.filter((p) => p.status !== 'WAITING').reduce((acc, p) => acc + p.latency, 0)
      ).toFixed(2),
      error: document.status === 'Failed' ? document.statusNote || 'Processing failed' : null,
      aborted: false,
      cancelled: false,
      page_count: document.pages,
      prompt_mode: taskMode,
      backend: 'llama-cpp (cuda)',
      pages: pagesList,
    };
  }, [document, taskMode]);

  const jsonString = useMemo(() => {
    return structuredJson ? JSON.stringify(structuredJson, null, 2) : '';
  }, [structuredJson]);

  const highlightedJsonContent = useMemo(() => {
    return jsonString ? highlightJson(jsonString) : null;
  }, [jsonString]);

  const charCount = currentTextContent.length;
  const wordCount = currentTextContent.trim() ? currentTextContent.trim().split(/\s+/).length : 0;

  const handleCopy = () => {
    if (!document || !isDoneOrTruncated) return;
    const textToCopy = activePreviewTab === 'json' ? jsonString : currentTextContent;
    navigator.clipboard.writeText(textToCopy);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Helper to render Formatted Markdown Preview cleanly
  const renderFormattedPreview = (rawText: string) => {
    if (!rawText.trim()) {
      return (
        <div className="text-[#5A6478] dark:text-[var(--text-2)] italic p-4 text-center text-[13px]">
          No content extracted for {taskMode} mode
        </div>
      );
    }

    const lines = rawText.split('\n');
    const elements: React.ReactNode[] = [];
    let tableBuffer: string[] = [];
    let inTable = false;

    const flushTable = (key: string) => {
      if (tableBuffer.length === 0) return;
      const rows = tableBuffer.map((r) =>
        r
          .split('|')
          .slice(1, -1)
          .map((c) => c.trim())
      );
      if (rows.length >= 2) {
        const header = rows[0];
        const dataRows = rows.slice(1).filter((r) => !r.every((c) => /^[-:]+$/.test(c)));

        elements.push(
          <div key={key} className="my-3 overflow-x-auto rounded-lg border border-[#8A94A6]/30 dark:border-[var(--border)] shadow-2xs bg-white dark:bg-[var(--bg-surface)]">
            <table className="w-full text-left border-collapse text-[12px]">
              <thead>
                <tr className="bg-[#F2EFE9] dark:bg-[var(--bg-elevated)] border-b border-[#8A94A6]/30 dark:border-[var(--border)] text-[#14213D] dark:text-[var(--text-1)] font-semibold">
                  {header.map((col, idx) => (
                    <th key={idx} className="px-3 py-2 border-r border-[#8A94A6]/20 dark:border-[var(--border)] last:border-r-0">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#8A94A6]/20 dark:divide-[var(--border)]">
                {dataRows.map((row, rIdx) => (
                  <tr key={rIdx} className={rIdx % 2 === 0 ? 'bg-white dark:bg-[var(--bg-surface)]' : 'bg-[#FAF9F5] dark:bg-[var(--bg-elevated)]'}>
                    {row.map((cell, cIdx) => (
                      <td key={cIdx} className="px-3 py-2 border-r border-[#8A94A6]/15 dark:border-[var(--border)] last:border-r-0 text-[#14213D] dark:text-[var(--text-1)]">
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }
      tableBuffer = [];
      inTable = false;
    };

    lines.forEach((line, index) => {
      const trimmed = line.trim();

      // Table line
      if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
        inTable = true;
        tableBuffer.push(trimmed);
        return;
      }

      if (inTable) {
        flushTable(`table-${index}`);
      }

      if (!trimmed) {
        elements.push(<div key={`empty-${index}`} className="h-2.5" />);
        return;
      }

      // LaTeX formula line
      if (trimmed.startsWith('\\') || trimmed.includes('\\text{') || trimmed.includes('\\sum')) {
        elements.push(
          <div
            key={`latex-${index}`}
            className="my-2 p-2.5 rounded-lg bg-[#0F766E]/5 dark:bg-[var(--accent)]/10 border border-[#0F766E]/20 dark:border-[var(--accent)]/30 font-mono text-[12px] text-[#0F766E] dark:text-[var(--accent)] overflow-x-auto"
          >
            <div className="text-[10px] uppercase font-semibold text-[#0F766E]/70 dark:text-[var(--accent)]/70 mb-1 font-sans">
              Mathematical Formula
            </div>
            <code>{trimmed}</code>
          </div>
        );
        return;
      }

      // Headings
      if (trimmed.startsWith('### ')) {
        elements.push(
          <h4 key={`h3-${index}`} className="text-[14px] font-bold text-[#14213D] dark:text-[var(--text-1)] mt-3 mb-1">
            {trimmed.replace('### ', '')}
          </h4>
        );
      } else if (trimmed.startsWith('## ')) {
        elements.push(
          <h3 key={`h2-${index}`} className="text-[15px] font-bold text-[#14213D] dark:text-[var(--text-1)] mt-3.5 mb-1.5 border-b border-black/5 dark:border-[var(--border)] pb-1">
            {trimmed.replace('## ', '')}
          </h3>
        );
      } else if (trimmed.startsWith('# ')) {
        elements.push(
          <h2 key={`h1-${index}`} className="text-[16px] font-bold text-[#14213D] dark:text-[var(--text-1)] mt-4 mb-2">
            {trimmed.replace('# ', '')}
          </h2>
        );
      } else if (trimmed.startsWith('---')) {
        elements.push(<hr key={`hr-${index}`} className="my-3 border-t border-[#8A94A6]/30 dark:border-[var(--border)]" />);
      } else {
        elements.push(
          <p key={`p-${index}`} className="text-[13px] leading-relaxed text-[#14213D] dark:text-[var(--text-1)] mb-1">
            {trimmed}
          </p>
        );
      }
    });

    if (inTable) {
      flushTable(`table-end`);
    }

    return elements;
  };

  return (
    <section 
      aria-label="Extracted text editor" 
      className="lg:col-span-4 flex flex-col bg-[#FBF9F4] dark:bg-[var(--bg-surface)] rounded-xl border border-[#8A94A6]/30 dark:border-[var(--border)] overflow-hidden h-full transition-colors"
    >
      {/* Pane Header: Document title & character/word counter badge */}
      <div className="h-12 px-4 border-b border-[#8A94A6]/25 dark:border-[var(--border)] flex items-center justify-between shrink-0 bg-[#FBF9F4] dark:bg-[var(--bg-surface)]">
        <div className="flex items-center gap-2 truncate">
          <h2 className="font-['IBM_Plex_Sans',sans-serif] text-sm font-semibold text-[#14213D] dark:text-[var(--text-1)] truncate" title={document?.name}>
            {document ? document.name : 'Extracted Text'}
          </h2>
        </div>
        {document && isCurrentPageViewedProcessed && (
          <span 
            className="text-xs font-mono tabular-nums text-[#5A6478] dark:text-[var(--text-2)] bg-black/[0.04] dark:bg-[var(--bg-elevated)] px-2 py-0.5 rounded border border-black/5 dark:border-[var(--border)] shrink-0"
            aria-label={`${charCount} characters, ${wordCount} words`}
          >
            {charCount.toLocaleString('en-US')} characters · {wordCount.toLocaleString('en-US')} words
          </span>
        )}
      </div>

      {/* Subheader: GLM-OCR Task Mode Selector & Primary Actions */}
      <div className="p-2.5 px-3 border-b border-black/[0.08] dark:border-[var(--border)] bg-white/40 dark:bg-[var(--bg-surface)] flex items-center justify-between gap-2 shrink-0">
        {/* Left: GLM-OCR Task Mode Selector */}
        <div className="relative inline-flex items-center">
          <div className="inline-flex items-center gap-1">
            <span className="text-2xs font-medium text-[#5A6478] dark:text-[var(--text-2)] uppercase tracking-wider hidden sm:inline mr-1">
              Task Mode:
            </span>
            <button
              type="button"
              onClick={() => setShowTaskModeMenu(!showTaskModeMenu)}
              className="h-8 px-2.5 bg-black/[0.04] dark:bg-[var(--bg-elevated)] hover:bg-black/[0.08] dark:hover:bg-[var(--bg-active)] text-[#14213D] dark:text-[var(--text-1)] rounded-lg text-xs font-medium flex items-center gap-1.5 border border-black/10 dark:border-[var(--border)] active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none"
              title="GLM-OCR prompt task preset (--prompt-mode)"
              aria-haspopup="true"
              aria-expanded={showTaskModeMenu}
            >
              <Sparkles className="w-3.5 h-3.5 text-[#0F766E] dark:text-[var(--accent)]" aria-hidden="true" />
              <span className="font-semibold">
                {taskModes.find((m) => m.mode === taskMode)?.label || 'Text Recognition'}
              </span>
              <ChevronDown className="w-3 h-3 text-[#5A6478] dark:text-[var(--text-2)]" aria-hidden="true" />
            </button>
          </div>

          {showTaskModeMenu && (
            <div 
              className="absolute left-0 top-9 w-64 bg-white dark:bg-[var(--bg-elevated)] rounded-lg border border-[#8A94A6]/30 dark:border-[var(--border)] py-1.5 z-30 shadow-lg text-[13px] origin-top-left animate-dropdown"
              role="menu"
              aria-label="GLM-OCR task mode options"
              onMouseLeave={() => setShowTaskModeMenu(false)}
            >
              <div className="px-3 py-1 text-2xs font-semibold uppercase tracking-wider text-[#5A6478] dark:text-[var(--text-2)] border-b border-black/5 dark:border-[var(--border)] mb-1">
                GLM-OCR Prompt Preset
              </div>
              {taskModes.map((tm) => (
                <button
                  key={tm.mode}
                  type="button"
                  onClick={() => {
                    setTaskMode(tm.mode);
                    setShowTaskModeMenu(false);
                  }}
                  className={`w-full text-left px-3 py-1.5 hover:bg-black/5 dark:hover:bg-[var(--bg-active)] flex items-center justify-between cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none ${
                    taskMode === tm.mode ? 'bg-[#0F766E]/10 dark:bg-[var(--accent)]/15' : ''
                  }`}
                  role="menuitem"
                >
                  <div>
                    <span className="font-semibold text-[#14213D] dark:text-[var(--text-1)] block text-xs">{tm.label}</span>
                    <span className="text-2xs text-[#5A6478] dark:text-[var(--text-2)] block">{tm.desc}</span>
                  </div>
                  {taskMode === tm.mode && (
                    <Check className="w-4 h-4 text-[#0F766E] dark:text-[var(--accent)] ml-2 shrink-0" aria-hidden="true" />
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Right: Primary Action Per State */}
        <div className="flex items-center gap-1.5 shrink-0">
          {!isEngineOnline ? (
            <button 
              className="h-8 px-3 rounded-lg border border-[#8A94A6] dark:border-[var(--border)] text-[#5A6478] dark:text-[var(--text-3)] cursor-not-allowed font-medium text-xs bg-transparent opacity-60 inline-flex items-center justify-center select-none" 
              disabled 
              type="button" 
              aria-label="Extraction disabled because engine is offline"
            >
              <span className="whitespace-nowrap">Extract Document</span>
            </button>
          ) : isEmptyState ? (
            <button 
              className="h-8 px-3.5 flex items-center bg-[#E4E2DD] dark:bg-[var(--bg-elevated)] text-[#5A6478] dark:text-[var(--text-3)] rounded-lg text-xs font-medium border border-[#8A94A6] dark:border-[var(--border)] cursor-not-allowed select-none" 
              disabled 
              type="button" 
              aria-label="Extraction disabled because no document is selected"
            >
              Extract Document
            </button>
          ) : document.status === 'Failed' ? (
            null
          ) : isDocOwnerOfRunningJob ? (
            <button 
              onClick={() => onCancelExtraction(document.id)}
              className="h-8 px-3.5 bg-[var(--danger)]/10 hover:bg-[var(--danger)]/18 active:bg-[var(--danger)]/25 text-[var(--danger)] border border-[var(--danger)]/30 font-semibold text-xs rounded-lg shadow-xs active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out flex items-center gap-1.5 cursor-pointer focus-visible:ring-2 focus-visible:ring-[var(--danger)] focus-visible:outline-none" 
              type="button" 
              aria-label="Cancel extraction"
            >
              <Ban className="w-4 h-4 leading-none" aria-hidden="true" />
              <span className="whitespace-nowrap">Cancel extraction</span>
            </button>
          ) : document.status === 'Waiting' ? (
            <div className="flex items-center gap-1.5">
              <span className="h-8 px-2.5 bg-black/[0.04] dark:bg-[var(--bg-elevated)] text-[#14213D] dark:text-[var(--text-1)] rounded-lg text-xs font-medium flex items-center gap-1.5 tabular-nums border border-black/5 dark:border-[var(--border)] select-none">
                <span className="w-1.5 h-1.5 rounded-full bg-[#0F766E] dark:bg-[var(--accent)]" />
                <span>Queued #{document.queuePosition || 1}</span>
              </span>
              <button
                type="button"
                onClick={() => onRemoveFromQueue(document.id)}
                className="h-8 px-2 text-[#4B5563] dark:text-[var(--text-2)] hover:text-red-700 hover:dark:text-[var(--danger)] hover:bg-red-50 hover:dark:bg-[var(--danger)]/10 rounded-md text-xs font-medium transition-colors cursor-pointer whitespace-nowrap focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none"
                title="Remove from queue"
              >
                <span>Remove</span>
              </button>
            </div>
          ) : isAnotherJobRunning && document.status === 'Not extracted' ? (
            <button 
              onClick={() => onAddToQueue(document.id)}
              className="h-8 px-3 bg-[#0F766E] hover:bg-[#115E59] active:bg-[#0d4f4b] text-white font-semibold text-xs rounded-lg shadow-xs active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out flex items-center gap-1.5 cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none" 
              type="button" 
              aria-label="Add to Queue"
            >
              <ListPlus className="w-4 h-4 text-white leading-none" aria-hidden="true" />
              <span className="whitespace-nowrap text-white">
                Add to Queue
              </span>
            </button>
          ) : document.status === 'Done' || document.status === 'Truncated' ? (
            <div className="flex items-center gap-2">
              {document.isReExtractionQueued ? (
                <div className="flex items-center gap-1.5">
                  <span className="h-8 px-2.5 bg-amber-500/10 dark:bg-[var(--warning)]/10 text-amber-800 dark:text-[var(--warning)] border border-amber-500/20 dark:border-[var(--warning)]/30 rounded-lg text-xs font-medium flex items-center gap-1.5 tabular-nums select-none">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-600 dark:bg-[var(--warning)]" />
                    <span>Queued #{document.queuePosition || 1}</span>
                  </span>
                  <button
                    type="button"
                    onClick={() => onRemoveFromQueue(document.id)}
                    className="h-8 px-2 text-[#4B5563] dark:text-[var(--text-2)] hover:text-red-700 hover:dark:text-[var(--danger)] hover:bg-red-50 hover:dark:bg-[var(--danger)]/10 rounded-md text-xs font-medium transition-colors cursor-pointer whitespace-nowrap focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none"
                    title="Remove from queue"
                  >
                    <span>Remove</span>
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => onReExtractDocument(document.id)}
                  className="h-8 px-2.5 text-[#4B5563] dark:text-[var(--text-1)] hover:text-[#14213D] dark:bg-[var(--bg-elevated)] dark:border dark:border-[var(--border)] hover:dark:bg-[var(--bg-active)] rounded-md text-xs font-medium active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out flex items-center gap-1 cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none"
                  title="Re-extract entire document with current settings"
                  type="button"
                >
                  <span>Re-extract</span>
                </button>
              )}

              {/* Clean Export Dropdown */}
              <div className="relative inline-flex">
                <button 
                  onClick={() => setShowExportMenu(!showExportMenu)}
                  className="h-8 px-3 bg-[#0F766E] hover:bg-[#115E59] active:bg-[#0d4f4b] text-white font-semibold text-xs rounded-lg shadow-xs active:scale-[0.96] active:translate-y-px active:brightness-95 transition-all duration-150 ease-out flex items-center gap-1.5 cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none" 
                  type="button" 
                  aria-haspopup="true" 
                  aria-expanded={showExportMenu}
                >
                  <Download className="w-4 h-4 text-white" aria-hidden="true" />
                  <span>Export</span>
                  <ChevronDown className="w-3.5 h-3.5 text-white/80" aria-hidden="true" />
                </button>

                {showExportMenu && (
                  <div 
                    className="absolute right-0 top-9 w-60 bg-white dark:bg-[var(--bg-elevated)] rounded-lg border border-[#8A94A6]/30 dark:border-[var(--border)] py-1.5 z-30 shadow-lg text-[13px] origin-top-right animate-dropdown" 
                    role="menu" 
                    aria-label="Export format options"
                    onMouseLeave={() => setShowExportMenu(false)}
                  >
                    <div className="px-3 py-1 text-2xs font-semibold uppercase tracking-wider text-[#5A6478] dark:text-[var(--text-2)] border-b border-black/5 dark:border-[var(--border)] mb-1">
                      Engine Output Format
                    </div>
                    {EXPORT_FORMATS.map((fmt) => (
                      <button 
                        key={fmt.ext}
                        onClick={() => {
                          setExportFormat(fmt.ext);
                          onExport(fmt.ext);
                          setShowExportMenu(false);
                        }}
                        className={`w-full text-left px-3 py-1.5 hover:bg-black/5 hover:dark:bg-[var(--bg-active)] flex items-center justify-between cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none ${
                          exportFormat === fmt.ext ? 'bg-black/[0.04] dark:bg-[var(--bg-active)]' : ''
                        }`} 
                        type="button" 
                        role="menuitem"
                      >
                        <div>
                          <span className="font-semibold text-[#14213D] dark:text-[var(--text-1)] block text-xs">{fmt.title}</span>
                          <span className="text-2xs text-[#4B5563] dark:text-[var(--text-2)] block">{fmt.desc}</span>
                        </div>
                        {exportFormat === fmt.ext && (
                          <Check className="w-4 h-4 text-[#0F766E] dark:text-[var(--accent)] ml-2 shrink-0" aria-hidden="true" />
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <button 
              onClick={() => onRunDocumentExtraction(document.id)}
              className="h-8 px-3.5 bg-[#0F766E] hover:bg-[#115E59] active:bg-[#0d4f4b] text-white font-semibold text-xs rounded-lg shadow-xs active:scale-[0.96] active:translate-y-px active:brightness-95 transition-all duration-150 ease-out flex items-center gap-1.5 cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none" 
              type="button" 
              aria-label="Extract Document"
            >
              <ScanText className="w-4 h-4 text-white leading-none" aria-hidden="true" />
              <span className="whitespace-nowrap text-white">
                Extract Document
              </span>
            </button>
          )}
        </div>
      </div>

      {/* Preview Display Tabs: Formatted Preview | Raw Markdown | JSON Tree */}
      <div className="px-3 py-1.5 border-b border-[#8A94A6]/20 dark:border-[var(--border)] bg-[#F4F2EC] dark:bg-[var(--bg-surface)] flex items-center justify-between shrink-0 transition-colors">
        <div 
          ref={tabContainerRef}
          className="relative inline-flex p-0.5 bg-black/[0.05] dark:bg-[var(--bg-base)] border border-black/5 dark:border-[var(--border)] rounded-lg gap-0.5"
          role="tablist"
          aria-label="Preview display modes"
        >
          <div 
            className="absolute top-0.5 bottom-0.5 rounded-md bg-white dark:bg-[var(--bg-elevated)] shadow-2xs dark:shadow-none transition-all duration-200 cubic-bezier(0.16, 1, 0.3, 1) pointer-events-none"
            style={{
              left: `${indicatorStyle.left}px`,
              width: `${indicatorStyle.width}px`,
              opacity: indicatorStyle.width > 0 ? 1 : 0,
            }}
          />
          <button
            ref={(el) => { tabRefs.current.formatted = el; }}
            type="button"
            role="tab"
            aria-selected={activePreviewTab === 'formatted'}
            onClick={() => setActivePreviewTab('formatted')}
            className={`relative z-10 px-2.5 py-1 rounded-md text-xs font-medium active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out flex items-center gap-1.5 cursor-pointer ${
              activePreviewTab === 'formatted'
                ? 'text-[#14213D] dark:text-[var(--text-1)]'
                : 'text-[#5A6478] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)]'
            }`}
          >
            <Layers className={`w-3.5 h-3.5 transition-colors duration-150 ${activePreviewTab === 'formatted' ? 'text-[#0F766E] dark:text-[var(--accent)]' : 'text-[#5A6478] dark:text-[var(--text-2)]'}`} aria-hidden="true" />
            <span>Formatted Preview</span>
          </button>

          <button
            ref={(el) => { tabRefs.current.raw = el; }}
            type="button"
            role="tab"
            aria-selected={activePreviewTab === 'raw'}
            onClick={() => setActivePreviewTab('raw')}
            className={`relative z-10 px-2.5 py-1 rounded-md text-xs font-medium active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out flex items-center gap-1.5 cursor-pointer ${
              activePreviewTab === 'raw'
                ? 'text-[#14213D] dark:text-[var(--text-1)]'
                : 'text-[#5A6478] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)]'
            }`}
          >
            <Code2 className={`w-3.5 h-3.5 transition-colors duration-150 ${activePreviewTab === 'raw' ? 'text-[#0F766E] dark:text-[var(--accent)]' : 'text-[#5A6478] dark:text-[var(--text-2)]'}`} aria-hidden="true" />
            <span>Raw Markdown</span>
          </button>

          <button
            ref={(el) => { tabRefs.current.json = el; }}
            type="button"
            role="tab"
            aria-selected={activePreviewTab === 'json'}
            onClick={() => setActivePreviewTab('json')}
            className={`relative z-10 px-2.5 py-1 rounded-md text-xs font-medium active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out flex items-center gap-1.5 cursor-pointer ${
              activePreviewTab === 'json'
                ? 'text-[#14213D] dark:text-[var(--text-1)]'
                : 'text-[#5A6478] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)]'
            }`}
          >
            <FileCode className={`w-3.5 h-3.5 transition-colors duration-150 ${activePreviewTab === 'json' ? 'text-[#0F766E] dark:text-[var(--accent)]' : 'text-[#5A6478] dark:text-[var(--text-2)]'}`} aria-hidden="true" />
            <span>JSON Tree</span>
          </button>
        </div>

        {/* Truncated warning badge if hit limit */}
        {document?.status === 'Truncated' && (
          <span className="text-2xs font-medium text-[#B45309] dark:text-[var(--warning)] bg-[#B45309]/10 dark:bg-[var(--warning)]/10 border border-transparent dark:border-[var(--warning)]/20 px-2 py-0.5 rounded flex items-center gap-1 shrink-0">
            <AlertTriangle className="w-3.5 h-3.5" aria-hidden="true" />
            Ceiling reached (4096 tokens)
          </span>
        )}
      </div>

      {/* Main Body */}
      {!isEngineOnline ? (
        <div className="flex-1 p-6 flex flex-col justify-center items-center overflow-y-auto bg-white dark:bg-[var(--bg-base)] min-h-0 transition-colors">
          <div className="w-full max-w-sm rounded-lg bg-[#FCFBF8] dark:bg-[var(--bg-elevated)] border border-red-200/90 dark:border-[var(--danger)]/30 p-5 shadow-xs flex flex-col items-start gap-4 my-auto">
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-[#DC2626] dark:bg-[var(--danger)] shrink-0" />
                <p className="text-sm font-semibold text-[#14213D] dark:text-[var(--text-1)]">
                  Local Engine Offline
                </p>
              </div>
              <p className="text-[13px] text-[#374151] dark:text-[var(--text-2)] leading-relaxed">
                The local llama-server backend is not currently running. Start the engine to run document OCR.
              </p>
            </div>
            <div className="flex items-center gap-3 pt-1">
              <button 
                onClick={onStartEngine}
                className="h-8.5 bg-[#0F766E] dark:bg-[var(--accent)] text-white dark:text-[var(--bg-base)] hover:bg-[#115E59] dark:hover:bg-[var(--accent)]/90 font-medium px-4 rounded-lg active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out shadow-xs flex items-center gap-1.5 text-[13px] cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] focus-visible:outline-none" 
                type="button" 
              >
                <Play className="w-4 h-4 text-white dark:text-[var(--bg-base)]" aria-hidden="true" />
                <span>Start Engine</span>
              </button>
              <button 
                onClick={onOpenSettings}
                className="h-8.5 border border-[#8A94A6] dark:border-[var(--border)] bg-white dark:bg-[var(--bg-elevated)] text-[#14213D] dark:text-[var(--text-1)] hover:bg-black/[0.02] dark:hover:bg-[var(--bg-active)] font-medium px-3.5 rounded-lg text-[13px] active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] focus-visible:outline-none" 
                type="button" 
              >
                Open Settings
              </button>
            </div>
          </div>
        </div>
      ) : isEmptyState ? (
        <div className="flex-1 p-4 flex flex-col min-h-0 bg-[#FBFAF7] dark:bg-[var(--bg-base)]">
          <div className="flex-1 border border-[#8A94A6]/30 dark:border-[var(--border)] rounded-xl bg-white dark:bg-[var(--bg-surface)] p-4 flex flex-col justify-center items-center text-center">
            <div className="flex flex-col items-center justify-center gap-2 select-none">
              <FileText className="w-8 h-8 text-[#5A6478] dark:text-[var(--text-3)] mb-1" aria-hidden="true" />
              <p className="text-sm text-[#374151] dark:text-[var(--text-2)] font-medium">
                No Extracted Content
              </p>
              <span className="text-xs text-[#5A6478] dark:text-[var(--text-3)]">
                Select a document from the queue and click Extract Document to generate text.
              </span>
            </div>
          </div>
        </div>
      ) : document.status === 'Failed' ? (
        <div className="flex-1 p-6 flex flex-col justify-center items-center overflow-y-auto bg-white dark:bg-[var(--bg-base)] min-h-0">
          <div className="w-full max-w-sm rounded-lg bg-red-50/80 dark:bg-[var(--bg-elevated)] border border-red-200 dark:border-[var(--danger)]/40 p-5 shadow-xs flex flex-col items-start gap-3 my-auto">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-5 h-5 text-red-700 dark:text-[var(--danger)]" aria-hidden="true" />
              <p className="text-sm font-semibold text-[#14213D] dark:text-[var(--text-1)]">
                Extraction Failed
              </p>
            </div>
            <p className="text-[13px] text-[#B91C1C] dark:text-[var(--danger)] leading-relaxed">
              {document.statusNote || 'Image was too large to process (exceeded pixel safety limit) and was not sent to the engine.'}
            </p>
            <p className="text-xs text-[#5A6478] dark:text-[var(--text-2)] pt-1 border-t border-red-200/60 dark:border-[var(--border)] w-full">
              Adjust image limits or prompt mode in Settings to retry.
            </p>
          </div>
        </div>
      ) : !isCurrentPageViewedProcessed ? (
        <div className="flex-1 p-6 flex flex-col justify-center items-center overflow-y-auto bg-white dark:bg-[var(--bg-base)] text-center min-h-0">
          <div className="max-w-xs space-y-2.5">
            <Hourglass className="w-8 h-8 text-[#5A6478] dark:text-[var(--text-3)] mx-auto mb-1" aria-hidden="true" />
            <p className="text-sm font-semibold text-[#14213D] dark:text-[var(--text-1)]">
              Page {currentPage} of {document.pages} not processed yet
            </p>
            <p className="text-xs text-[#5A6478] dark:text-[var(--text-2)] leading-relaxed">
              {document.status === 'Processing'
                ? `The engine is currently processing page ${processedPages}. This page will appear once processed.`
                : 'This document is waiting in queue to be processed.'}
            </p>
          </div>
        </div>
      ) : (
        /* Text / JSON Body Container */
        <div className="flex-1 p-3.5 bg-white dark:bg-[var(--bg-base)] flex flex-col overflow-hidden min-h-0 transition-colors">
          {/* Editorial Multi-page divider */}
          <div className={`py-1 px-3 mb-2 rounded text-xs font-mono flex justify-between items-center shrink-0 border ${
            isCurrentPageTruncated
              ? 'bg-amber-50/80 dark:bg-[var(--warning)]/10 border-amber-300 dark:border-[var(--warning)]/30 text-[#92400E] dark:text-[var(--warning)]'
              : 'bg-[#F2EFE9] dark:bg-[var(--bg-elevated)] border-[#8A94A6]/30 dark:border-[var(--border)] text-[#4B5563] dark:text-[var(--text-2)]'
          }`}>
            <div className="flex items-center gap-2">
              <span className="font-medium tracking-tight">--- Page {currentPage} of {document.pages} ---</span>
              {isCurrentPageTruncated && (
                <span className="bg-[#B45309]/15 dark:bg-[var(--warning)]/20 text-[#92400E] dark:text-[var(--warning)] font-sans font-semibold text-2xs px-1.5 py-0.5 rounded">
                  Ceiling reached (4096 tokens)
                </span>
              )}
            </div>
            <span className="text-[#0F766E] dark:text-[var(--accent)] text-2xs font-sans font-medium">
              {document.status === 'Done' ? 'Done' : document.status === 'Truncated' ? 'Truncated' : `Processing page ${currentPage}...`}
            </span>
          </div>

          {/* Active Preview View */}
          <div className="flex-1 flex flex-col overflow-hidden min-h-0">
            {activePreviewTab === 'formatted' && (
              <div 
                className="flex-1 overflow-y-auto p-3.5 rounded-lg border border-[#8A94A6]/25 dark:border-[var(--border)] bg-[#FAF9F5] dark:bg-[var(--bg-elevated)] select-text font-sans text-[#14213D] dark:text-[var(--text-1)] transition-colors animate-fade-in"
                tabIndex={0}
                role="region"
                aria-label="Formatted reading view"
              >
                {renderFormattedPreview(currentTextContent)}
                <div className="mt-4 pt-2 border-t border-[#8A94A6]/20 dark:border-[var(--border)] text-2xs text-[#5A6478] dark:text-[var(--text-2)] italic">
                  Visual rendering of markdown output. Select Raw Markdown to edit or inspect source.
                </div>
              </div>
            )}

            {activePreviewTab === 'raw' && (
              <textarea 
                id="ocr-editor"
                spellCheck="false" 
                role="textbox" 
                readOnly
                aria-label="OCR extracted text (Raw Markdown)"
                value={currentTextContent}
                className="w-full flex-1 resize-none p-3.5 rounded-lg border border-[#8A94A6]/35 dark:border-[var(--border)] bg-[#FAF9F5] dark:bg-[var(--bg-base)] text-[#14213D] dark:text-[var(--text-1)] text-[13px] leading-relaxed font-mono select-text outline-none focus:border-[#0F766E] dark:focus:border-[var(--accent)] selection:bg-[#0F766E]/20 dark:selection:bg-[var(--accent)]/20 animate-fade-in" 
              />
            )}

            {activePreviewTab === 'json' && (
              <div 
                className="w-full flex-1 overflow-auto p-3.5 rounded-lg border border-[#8A94A6]/30 dark:border-[var(--border)] bg-[#FAF9F5] dark:bg-[var(--bg-base)] text-[#14213D] dark:text-[var(--text-1)] text-xs leading-relaxed font-mono select-text selection:bg-[#0F766E]/20 dark:selection:bg-[var(--accent)]/20 animate-fade-in"
                tabIndex={0}
                role="region"
                aria-label="Structured JSON output tree"
              >
                <pre className="whitespace-pre font-mono">{highlightedJsonContent}</pre>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Actions Footer */}
      <div className="px-3.5 py-2.5 border-t border-[#8A94A6]/25 dark:border-[var(--border)] bg-[#FBFAF7] dark:bg-[var(--bg-surface)] flex items-center justify-between shrink-0 transition-colors">
        <div className="flex items-center gap-2 shrink-0">
          <button 
            disabled={!isDoneOrTruncated}
            onClick={handleCopy}
            className={`h-8 px-3 rounded-lg border active:scale-90 active:translate-y-px transition-all duration-100 ease-out text-xs font-medium flex items-center gap-1.5 cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] focus-visible:outline-none ${
              copied
                ? 'bg-emerald-50 dark:bg-[var(--success)]/10 border-emerald-300 dark:border-[var(--success)]/30 text-emerald-800 dark:text-[var(--success)] shadow-xs'
                : 'border-[#8A94A6] dark:border-[var(--border)] hover:border-[#14213D] dark:hover:border-[var(--border-strong)] bg-white dark:bg-[var(--bg-elevated)] text-[#14213D] dark:text-[var(--text-1)] hover:bg-black/[0.02] dark:hover:bg-[var(--bg-active)] disabled:opacity-40 disabled:cursor-not-allowed'
            }`}
            type="button" 
            aria-label={copied ? 'Copied to clipboard' : activePreviewTab === 'json' ? 'Copy JSON' : 'Copy'}
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-700 dark:text-[var(--success)] leading-none" aria-hidden="true" />
                <span className="font-semibold text-emerald-800 dark:text-[var(--success)]">Copied to clipboard</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5 text-[#5A6478] dark:text-[var(--text-2)] leading-none" aria-hidden="true" />
                <span>{activePreviewTab === 'json' ? 'Copy JSON' : 'Copy'}</span>
              </>
            )}
          </button>
        </div>

        {/* Read-only output indicator matching engine reality */}
        <div className="text-xs text-[#5A6478] dark:text-[var(--text-2)] font-medium select-none flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-[#0F766E] dark:bg-[var(--accent)]" />
          <span>Read-only output buffer</span>
        </div>
      </div>
    </section>
  );
};
