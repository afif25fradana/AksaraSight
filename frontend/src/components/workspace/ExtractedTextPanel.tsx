import React, { useState, useMemo, useEffect, useRef } from 'react';
import { Check, Copy, Ban, ListPlus, ScanText, AlertTriangle, Play, FileText, AlertCircle, Hourglass, Layers, Code2, FileCode, RefreshCw } from 'lucide-react';
import { DocumentItem, PromptMode, OutputFormatType } from '../../types';
import { MarkdownRenderer } from '../renderers/MarkdownRenderer';
import { highlightJson } from '../renderers/jsonHighlighter';
import { ExtractionOptionsPopover } from './ExtractionOptionsPopover';
import { ExportDropdown } from './ExportDropdown';

export interface ExtractedTextPanelProps {
  document: DocumentItem | null; runningJobDocId: string | null; isEngineOnline: boolean;
  isTransitioning?: boolean; selectedDpi?: number; onDpiChange?: (dpi: number) => void;
  onStartEngine: () => void; onOpenSettings: () => void; onExport: (format: OutputFormatType) => void;
  onRunDocumentExtraction: (docId: string, promptMode?: PromptMode, dpi?: number) => void;
  onAddToQueue: (docId: string) => void; onRemoveFromQueue: (docId: string) => void;
  onCancelExtraction: (docId: string) => void;
  onReExtractDocument: (docId: string, promptMode?: PromptMode, dpi?: number) => void;
}

type PreviewTab = 'formatted' | 'raw' | 'json';

export const ExtractedTextPanel: React.FC<ExtractedTextPanelProps> = ({
  document, runningJobDocId, isEngineOnline, isTransitioning = false, selectedDpi,
  onDpiChange, onStartEngine, onOpenSettings, onExport, onRunDocumentExtraction,
  onAddToQueue, onRemoveFromQueue, onCancelExtraction, onReExtractDocument,
}) => {
  const [localDpi, setLocalDpi] = useState<number>(100);
  const currentDpi = selectedDpi !== undefined ? selectedDpi : localDpi;
  const [exportFormat, setExportFormat] = useState<OutputFormatType>('docx');
  const [showExportMenu, setShowExportMenu] = useState(false), [copied, setCopied] = useState(false);
  const [taskMode, setTaskMode] = useState<PromptMode>('text'), [showExtractionOptions, setShowExtractionOptions] = useState(false);
  const [activePreviewTab, setActivePreviewTab] = useState<PreviewTab>('formatted');
  const copyTimeoutRef = useRef<any>(null);

  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current) {
        clearTimeout(copyTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (document?.promptMode) setTaskMode(document.promptMode);
  }, [document?.id, document?.promptMode]);

  const isEmptyState = !document;
  const isDocOwnerOfRunningJob = Boolean(document && runningJobDocId === document.id);
  const isAnotherJobRunning = Boolean(runningJobDocId && document && runningJobDocId !== document.id);
  const hasExtractedContent = Boolean(document && ((document.extractedText && document.extractedText.trim().length > 0) || (document.pagesData && Object.values(document.pagesData).some((p) => Boolean(p.text && p.text.trim())))));
  const isPartialFailure = Boolean(document && document.status === 'Failed' && hasExtractedContent);
  const isTotalFailure = Boolean(document && document.status === 'Failed' && !hasExtractedContent);
  const canExportOrCopy = Boolean(
    isEngineOnline && document && !isDocOwnerOfRunningJob &&
    (document.status === 'Done' || document.status === 'Truncated' || isPartialFailure) && hasExtractedContent
  );

  const currentPage = document?.currentPage || 1;
  const processedPages = document?.processedPages || 0;
  const isCurrentPageViewedProcessed = Boolean(
    document && (document.status === 'Done' || document.status === 'Truncated' || isPartialFailure || currentPage <= processedPages)
  );
  const currentPageData = document?.pagesData?.[currentPage];

  const currentTextContent = useMemo(() => {
    if (!document) return '';
    if (taskMode === 'table') return currentPageData?.table || document.extractedTable || document.extractedText || '';
    if (taskMode === 'formula') return currentPageData?.formula || document.extractedFormula || document.extractedText || '';
    return currentPageData?.text || document.extractedText || '';
  }, [document, currentPageData, taskMode]);

  const { charCount, wordCount } = useMemo(() => {
    if (!currentTextContent) return { charCount: 0, wordCount: 0 };
    return { charCount: currentTextContent.length, wordCount: currentTextContent.trim() ? currentTextContent.trim().split(/\s+/).length : 0 };
  }, [currentTextContent]);

  const jsonString = useMemo(() => {
    if (!document) return '';
    const totalPages = document.pages || 1;
    const pagesList = [];
    for (let i = 1; i <= totalPages; i++) {
      const pData = document.pagesData?.[i];
      const isPageTruncated = Boolean(pData?.isTruncated);
      const pageStatus = pData
        ? (isPageTruncated ? 'PARTIAL' : 'SUCCESS')
        : (document.status === 'Failed' ? 'FAILED' : 'PENDING');
      pagesList.push({
        page_num: i,
        status: pageStatus,
        latency: pData?.latency ?? 0.0,
        tokens: pData?.tokens ?? 0,
        markdown: pData?.text || '',
        error: null,
        raw_json: null,
        truncated: isPageTruncated,
      });
    }

    const docStatus = document.status === 'Done'
      ? 'SUCCESS'
      : document.status === 'Truncated'
      ? 'PARTIAL'
      : document.status === 'Failed'
      ? 'FAILED'
      : document.status;

    const totalDuration = pagesList.reduce((acc, p) => acc + (p.latency || 0), 0);
    const ocrResult = {
      file_path: document.name,
      status: docStatus,
      total_duration: Number(totalDuration.toFixed(2)),
      error: document.status === 'Failed' ? (document.statusNote || 'Extraction failed') : null,
      aborted: false,
      cancelled: document.statusNote === 'Job cancelled',
      page_count: totalPages,
      pages: pagesList,
    };
    return JSON.stringify(ocrResult, null, 2);
  }, [document]);

  const handleCopy = async () => {
    if (!document || !canExportOrCopy) return;
    try {
      await navigator.clipboard.writeText(activePreviewTab === 'json' ? jsonString : currentTextContent);
      setCopied(true);
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
      copyTimeoutRef.current = setTimeout(() => setCopied(false), 2000);
    } catch (err) { console.error('Copy failed:', err); }
  };

  return (
    <section aria-label="Extracted text editor" className="lg:col-span-4 flex flex-col bg-[#FBF9F4] dark:bg-[var(--bg-surface)] rounded-xl border border-[#8A94A6]/30 dark:border-[var(--border)] overflow-hidden h-full transition-colors">
      <div className="h-12 px-4 border-b border-[#8A94A6]/25 dark:border-[var(--border)] flex items-center justify-between shrink-0">
        <h2 className="font-['IBM_Plex_Sans',sans-serif] text-sm font-semibold text-[#14213D] dark:text-[var(--text-1)] truncate" title={document?.name}>
          {document ? document.name : 'Extracted Text'}
        </h2>
        {document && isCurrentPageViewedProcessed && (
          <span className="text-xs font-mono tabular-nums text-[#5A6478] dark:text-[var(--text-2)] bg-black/[0.04] dark:bg-[var(--bg-elevated)] px-2 py-0.5 rounded border border-black/5 dark:border-[var(--border)] shrink-0" aria-label={`${charCount} characters, ${wordCount} words`}>
            {charCount.toLocaleString('en-US')} characters · {wordCount.toLocaleString('en-US')} words
          </span>
        )}
      </div>

      <div className="p-2.5 px-3 border-b border-black/[0.08] dark:border-[var(--border)] bg-white/40 dark:bg-[var(--bg-surface)] flex items-center justify-between gap-2 shrink-0">
        <ExtractionOptionsPopover
          taskMode={taskMode} currentDpi={currentDpi}
          onSelectMode={setTaskMode} onSelectDpi={(dpi) => { setLocalDpi(dpi); onDpiChange?.(dpi); }}
          isOpen={showExtractionOptions} onToggleOpen={() => setShowExtractionOptions(!showExtractionOptions)}
          onClose={() => setShowExtractionOptions(false)}
        />

        <div className="flex items-center gap-1.5 shrink-0">
          {!isEngineOnline ? (
            <button className="h-8 px-3 rounded-lg border border-[#8A94A6] dark:border-[var(--border)] text-[#5A6478] dark:text-[var(--text-3)] cursor-not-allowed font-medium text-xs bg-transparent opacity-60" disabled type="button" aria-label="Extraction disabled because engine is offline">
              <span className="whitespace-nowrap">Extract Document</span>
            </button>
          ) : isEmptyState ? (
            <button className="h-8 px-3.5 flex items-center bg-[#E4E2DD] dark:bg-[var(--bg-elevated)] text-[#5A6478] dark:text-[var(--text-3)] rounded-lg text-xs font-medium border border-[#8A94A6] dark:border-[var(--border)] cursor-not-allowed" disabled type="button" aria-label="Extraction disabled because no document is selected">
              Extract Document
            </button>
          ) : isTotalFailure ? (
            <button onClick={() => onReExtractDocument(document.id, taskMode, currentDpi)} className="h-8 px-3.5 bg-[#0F766E] hover:bg-[#115E59] active:bg-[#0d4f4b] text-white font-semibold text-xs rounded-lg shadow-xs flex items-center gap-1.5 cursor-pointer" type="button" aria-label="Retry extraction">
              <Play className="w-3.5 h-3.5 fill-current" aria-hidden="true" /><span>Retry extraction</span>
            </button>
          ) : isDocOwnerOfRunningJob ? (
            <button onClick={() => onCancelExtraction(document.id)} className="h-8 px-3.5 bg-[var(--danger)]/10 text-[var(--danger)] border border-[var(--danger)]/30 font-semibold text-xs rounded-lg flex items-center gap-1.5 cursor-pointer" type="button" aria-label="Cancel extraction">
              <Ban className="w-4 h-4" aria-hidden="true" /><span>Cancel extraction</span>
            </button>
          ) : document.status === 'Waiting' ? (
            <div className="flex items-center gap-1.5">
              <span className="h-8 px-2.5 bg-black/[0.04] dark:bg-[var(--bg-elevated)] text-[#14213D] dark:text-[var(--text-1)] rounded-lg text-xs font-medium flex items-center gap-1.5 border border-black/5 dark:border-[var(--border)]">
                <span className="w-1.5 h-1.5 rounded-full bg-[#0F766E] dark:bg-[var(--accent)]" /><span>Queued #{document.queuePosition || 1}</span>
              </span>
              <button type="button" onClick={() => onRemoveFromQueue(document.id)} className="h-8 px-2 text-[#4B5563] dark:text-[var(--text-2)] hover:text-red-700 rounded-md text-xs font-medium cursor-pointer" title="Remove from queue">
                <span>Remove</span>
              </button>
            </div>
          ) : isAnotherJobRunning && document.status === 'Not extracted' ? (
            <button onClick={() => onAddToQueue(document.id)} className="h-8 px-3 bg-[#0F766E] text-white font-semibold text-xs rounded-lg flex items-center gap-1.5 cursor-pointer" type="button" aria-label="Add to Queue">
              <ListPlus className="w-4 h-4 text-white" aria-hidden="true" /><span className="text-white">Add to Queue</span>
            </button>
          ) : document.status === 'Done' || document.status === 'Truncated' || isPartialFailure ? (
            <div className="flex items-center gap-2">
              {document.isReExtractionQueued ? (
                <div className="flex items-center gap-1.5">
                  <span className="h-8 px-2.5 bg-amber-500/10 text-amber-800 dark:text-[var(--warning)] border border-amber-500/20 rounded-lg text-xs font-medium flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-600" /><span>Queued #{document.queuePosition || 1}</span>
                  </span>
                  <button type="button" onClick={() => onRemoveFromQueue(document.id)} className="h-8 px-2 text-[#4B5563] hover:text-red-700 text-xs font-medium cursor-pointer" title="Remove from queue">Remove</button>
                </div>
              ) : (
                <button onClick={() => onReExtractDocument(document.id, taskMode, currentDpi)} className="h-8 px-2.5 text-[#4B5563] dark:text-[var(--text-1)] dark:bg-[var(--bg-elevated)] rounded-md text-xs font-medium flex items-center gap-1 cursor-pointer" title="Re-extract entire document with current settings" type="button">
                  <span>{isPartialFailure ? 'Retry extraction' : 'Re-extract'}</span>
                </button>
              )}
              <ExportDropdown isOpen={showExportMenu} onToggleOpen={() => setShowExportMenu(!showExportMenu)} onClose={() => setShowExportMenu(false)} onExport={onExport} selectedFormat={exportFormat} onSelectFormat={setExportFormat} />
            </div>
          ) : (
            <button onClick={() => onRunDocumentExtraction(document.id, taskMode, currentDpi)} className="h-8 px-3.5 bg-[#0F766E] hover:bg-[#115E59] text-white font-semibold text-xs rounded-lg flex items-center gap-1.5 cursor-pointer" type="button" aria-label="Extract Document">
              <ScanText className="w-4 h-4 text-white" aria-hidden="true" /><span className="text-white">Extract Document</span>
            </button>
          )}
        </div>
      </div>

      <div className="px-3 py-1.5 border-b border-[#8A94A6]/20 dark:border-[var(--border)] bg-[#F4F2EC] dark:bg-[var(--bg-surface)] flex items-center justify-between shrink-0">
        <div className="inline-flex p-0.5 bg-black/[0.05] dark:bg-[var(--bg-base)] border border-black/5 dark:border-[var(--border)] rounded-lg gap-0.5" role="tablist" aria-label="Preview display modes">
          {(['formatted', 'raw', 'json'] as PreviewTab[]).map((tab) => (
            <button key={tab} type="button" role="tab" aria-selected={activePreviewTab === tab} onClick={() => setActivePreviewTab(tab)} className={`px-2.5 py-1 rounded-md text-xs font-medium flex items-center gap-1.5 cursor-pointer ${activePreviewTab === tab ? 'bg-white dark:bg-[var(--bg-elevated)] text-[#14213D] dark:text-[var(--text-1)] shadow-2xs' : 'text-[#5A6478] dark:text-[var(--text-2)] hover:text-[#14213D]'}`}>
              {tab === 'formatted' ? <Layers className="w-3.5 h-3.5" /> : tab === 'raw' ? <Code2 className="w-3.5 h-3.5" /> : <FileCode className="w-3.5 h-3.5" />}
              <span>{tab === 'formatted' ? 'Formatted Preview' : tab === 'raw' ? 'Raw Markdown' : 'JSON Tree'}</span>
            </button>
          ))}
        </div>
        {document?.status === 'Truncated' && (
          <span className="text-2xs font-medium text-[#B45309] dark:text-[var(--warning)] bg-[#B45309]/10 px-2 py-0.5 rounded flex items-center gap-1 shrink-0">
            <AlertTriangle className="w-3.5 h-3.5" aria-hidden="true" />Ceiling reached (4096 tokens)
          </span>
        )}
      </div>

      {!isEngineOnline ? (
        <div className="flex-1 p-6 flex flex-col justify-center items-center overflow-y-auto bg-white dark:bg-[var(--bg-base)] min-h-0">
          <div className="w-full max-w-sm rounded-lg bg-[#FCFBF8] dark:bg-[var(--bg-elevated)] border border-red-200/90 dark:border-[var(--danger)]/30 p-5 shadow-xs flex flex-col items-start gap-4 my-auto">
            <div className="space-y-1.5">
              <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-[#DC2626] dark:bg-[var(--danger)] shrink-0" /><p className="text-sm font-semibold text-[#14213D] dark:text-[var(--text-1)]">Local Engine Offline</p></div>
              <p className="text-[13px] text-[#374151] dark:text-[var(--text-2)] leading-relaxed">The local llama-server backend is not currently running. Start the engine to run document OCR.</p>
            </div>
            <div className="flex items-center gap-3 pt-1">
              <button onClick={onStartEngine} disabled={isTransitioning} className="h-8.5 bg-[#0F766E] text-white hover:bg-[#115E59] font-medium px-4 rounded-lg flex items-center gap-1.5 text-[13px] cursor-pointer" type="button">
                {isTransitioning ? <><RefreshCw className="w-4 h-4 animate-spin text-white" aria-hidden="true" /><span>Starting...</span></> : <><Play className="w-4 h-4 text-white" aria-hidden="true" /><span>Start Engine</span></>}
              </button>
              <button onClick={onOpenSettings} className="h-8.5 border border-[#8A94A6] dark:border-[var(--border)] bg-white dark:bg-[var(--bg-elevated)] font-medium px-3.5 rounded-lg text-[13px] cursor-pointer" type="button">Open Settings</button>
            </div>
          </div>
        </div>
      ) : isEmptyState ? (
        <div className="flex-1 p-4 flex flex-col min-h-0 bg-[#FBFAF7] dark:bg-[var(--bg-base)]">
          <div className="flex-1 border border-[#8A94A6]/30 dark:border-[var(--border)] rounded-xl bg-white dark:bg-[var(--bg-surface)] p-4 flex flex-col justify-center items-center text-center">
            <FileText className="w-8 h-8 text-[#5A6478] dark:text-[var(--text-3)] mb-1" aria-hidden="true" />
            <p className="text-sm text-[#374151] dark:text-[var(--text-2)] font-medium">No Extracted Content</p>
            <span className="text-xs text-[#5A6478] dark:text-[var(--text-3)]">Select a document from the queue and click Extract Document to generate text.</span>
          </div>
        </div>
      ) : isTotalFailure ? (
        <div className="flex-1 p-6 flex flex-col justify-center items-center overflow-y-auto bg-white dark:bg-[var(--bg-base)] min-h-0">
          <div className="w-full max-w-sm rounded-lg bg-red-50/80 dark:bg-[var(--bg-elevated)] border border-red-200 p-5 shadow-xs flex flex-col items-start gap-3 my-auto">
            <div className="flex items-center gap-2"><AlertCircle className="w-5 h-5 text-red-700 dark:text-[var(--danger)]" aria-hidden="true" /><p className="text-sm font-semibold text-[#14213D] dark:text-[var(--text-1)]">Extraction Failed</p></div>
            <p className="text-[13px] text-[#B91C1C] dark:text-[var(--danger)] leading-relaxed">{document.statusNote || 'Extraction failed'}</p>
            <button type="button" onClick={() => onReExtractDocument(document.id, taskMode, currentDpi)} className="mt-1 h-8 px-3.5 bg-red-700 text-white font-medium text-xs rounded-lg flex items-center gap-1.5 cursor-pointer">
              <Play className="w-3.5 h-3.5 fill-current" aria-hidden="true" /><span>Retry extraction</span>
            </button>
          </div>
        </div>
      ) : !isCurrentPageViewedProcessed ? (
        <div className="flex-1 p-6 flex flex-col justify-center items-center overflow-y-auto bg-white dark:bg-[var(--bg-base)] text-center min-h-0">
          <Hourglass className="w-8 h-8 text-[#5A6478] dark:text-[var(--text-3)] mx-auto mb-1" aria-hidden="true" />
          <p className="text-sm font-semibold text-[#14213D] dark:text-[var(--text-1)]">Page {currentPage} of {document.pages} not processed yet</p>
          <p className="text-xs text-[#5A6478] dark:text-[var(--text-2)]">{document.status === 'Processing' ? `Processing page ${processedPages}...` : 'Waiting in queue...'}</p>
        </div>
      ) : (
        <div className="flex-1 p-3.5 bg-white dark:bg-[var(--bg-base)] flex flex-col overflow-hidden min-h-0 transition-colors">
          {isPartialFailure && (
            <div role="alert" className="mb-3 p-3 bg-amber-50/90 dark:bg-[var(--warning)]/10 border border-amber-300 dark:border-[var(--warning)]/30 rounded-lg flex items-center justify-between text-xs gap-3 shrink-0">
              <div className="flex items-center gap-2 text-amber-900 dark:text-[var(--warning)] min-w-0">
                <AlertTriangle className="w-4 h-4 shrink-0 text-amber-600 dark:text-[var(--warning)]" aria-hidden="true" />
                <span className="truncate">
                  <strong className="font-semibold">Incomplete extraction:</strong>{' '}
                  {document.statusNote || 'Processing encountered an error before all pages finished.'}
                </span>
              </div>
              <button type="button" onClick={() => onReExtractDocument(document.id, taskMode, currentDpi)} className="px-2.5 py-1 bg-amber-600 hover:bg-amber-700 text-white font-medium rounded text-xs transition-colors shrink-0 cursor-pointer">
                Retry
              </button>
            </div>
          )}
          <div className="py-1 px-3 mb-2 rounded text-xs font-mono flex justify-between items-center shrink-0 border bg-[#F2EFE9] dark:bg-[var(--bg-elevated)] border-[#8A94A6]/30 dark:border-[var(--border)] text-[#4B5563] dark:text-[var(--text-2)]">
            <span className="font-medium">--- Page {currentPage} of {document.pages} ---</span>
            <span className="text-[#0F766E] dark:text-[var(--accent)] text-2xs font-sans font-medium" aria-live="polite">{document.status}</span>
          </div>
          <div className="flex-1 flex flex-col overflow-hidden min-h-0">
            {activePreviewTab === 'formatted' && (
              <div className="flex-1 overflow-y-auto p-3.5 rounded-lg border border-[#8A94A6]/25 dark:border-[var(--border)] bg-[#FAF9F5] dark:bg-[var(--bg-elevated)] select-text text-[#14213D] dark:text-[var(--text-1)] animate-fade-in" tabIndex={0} role="region" aria-label="Formatted reading view">
                <MarkdownRenderer content={currentTextContent} taskMode={taskMode} />
              </div>
            )}
            {activePreviewTab === 'raw' && (
              <textarea id="ocr-editor" spellCheck="false" role="textbox" readOnly aria-label="OCR extracted text (Raw Markdown)" value={currentTextContent} className="w-full flex-1 resize-none p-3.5 rounded-lg border border-[#8A94A6]/35 dark:border-[var(--border)] bg-[#FAF9F5] dark:bg-[var(--bg-base)] text-[#14213D] dark:text-[var(--text-1)] text-[13px] font-mono outline-none focus:border-[#0F766E] animate-fade-in" />
            )}
            {activePreviewTab === 'json' && (
              <div className="w-full flex-1 overflow-auto p-3.5 rounded-lg border border-[#8A94A6]/30 dark:border-[var(--border)] bg-[#FAF9F5] dark:bg-[var(--bg-base)] text-xs font-mono animate-fade-in" tabIndex={0} role="region" aria-label="Structured JSON output tree">
                <pre className="whitespace-pre font-mono">{highlightJson(jsonString)}</pre>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="px-3.5 py-2.5 border-t border-[#8A94A6]/25 dark:border-[var(--border)] bg-[#FBFAF7] dark:bg-[var(--bg-surface)] flex items-center justify-between shrink-0">
        <button disabled={!canExportOrCopy} onClick={handleCopy} className={`h-8 px-3 rounded-lg border text-xs font-medium flex items-center gap-1.5 cursor-pointer ${copied ? 'bg-emerald-50 border-emerald-300 text-emerald-800' : 'border-[#8A94A6] dark:border-[var(--border)] bg-white dark:bg-[var(--bg-elevated)] text-[#14213D] dark:text-[var(--text-1)] disabled:opacity-40 disabled:cursor-not-allowed'}`} type="button" aria-label={copied ? 'Copied to clipboard' : activePreviewTab === 'json' ? 'Copy JSON' : 'Copy'}>
          {copied ? <><Check className="w-3.5 h-3.5 text-emerald-700" aria-hidden="true" /><span className="font-semibold text-emerald-800">Copied to clipboard</span></> : <><Copy className="w-3.5 h-3.5" aria-hidden="true" /><span>{activePreviewTab === 'json' ? 'Copy JSON' : 'Copy'}</span></>}
        </button>
        <div className="text-xs text-[#5A6478] dark:text-[var(--text-2)] font-medium select-none flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-[#0F766E] dark:bg-[var(--accent)]" /><span>Read-only output buffer</span>
        </div>
      </div>
    </section>
  );
};
