import React, { useState } from 'react';
import { ScrollText, ChevronLeft, ChevronRight, Minus, Plus, Maximize2 } from 'lucide-react';
import { DocumentItem } from '../types';

interface DocumentPreviewPanelProps {
  document: DocumentItem | null;
  onPageChange: (newPage: number) => void;
}

export const DocumentPreviewPanel: React.FC<DocumentPreviewPanelProps> = ({
  document,
  onPageChange,
}) => {
  const [zoomLevel, setZoomLevel] = useState<number>(100);

  const handleZoomIn = () => {
    setZoomLevel((prev) => Math.min(prev + 25, 200));
  };

  const handleZoomOut = () => {
    setZoomLevel((prev) => Math.max(prev - 25, 50));
  };

  const handleZoomReset = () => {
    setZoomLevel(100);
  };

  if (!document) {
    return (
      <main 
        aria-label="Document preview empty" 
        className="lg:col-span-5 flex flex-col bg-[#FAF9F5] dark:bg-[var(--bg-surface)] rounded-xl border border-[#8A94A6]/30 dark:border-[var(--border)] overflow-hidden h-full transition-colors"
      >
        <div className="h-12 px-4 border-b border-[#8A94A6]/25 dark:border-[var(--border)] flex items-center justify-between shrink-0 bg-[#FAF9F5] dark:bg-[var(--bg-surface)]">
          <h2 className="font-['IBM_Plex_Sans',sans-serif] text-[14px] font-semibold text-[#14213D] dark:text-[var(--text-1)]">
            Document Preview
          </h2>
        </div>
        <div className="h-11 px-3 border-b border-[#8A94A6]/25 dark:border-[var(--border)] flex items-center justify-between bg-white/70 dark:bg-[var(--bg-surface)]/90 backdrop-blur-sm shrink-0 text-[#5A6478] dark:text-[var(--text-2)] text-[13px] select-none">
          <div className="flex items-center gap-1 opacity-50">
            <span className="h-7 px-2 flex items-center gap-1 font-medium text-[12.5px]">Previous</span>
            <span className="px-2 text-[12.5px] tabular-nums">0 of 0</span>
            <span className="h-7 px-2 flex items-center gap-1 font-medium text-[12.5px]">Next</span>
          </div>
          <div className="flex items-center gap-1 opacity-50">
            <span className="h-7 px-2 flex items-center font-medium text-[12.5px]">Fit</span>
          </div>
        </div>
        <div className="flex-1 bg-[#EAE8E1]/60 dark:bg-[var(--bg-base)] p-6 flex flex-col items-center justify-center text-center select-none">
          <div className="w-12 h-12 rounded-full bg-[#14213D]/[0.05] dark:bg-white/[0.05] border border-[#14213D]/[0.08] dark:border-[var(--border)] flex items-center justify-center mb-3 text-[#5A6478] dark:text-[var(--text-3)] shadow-xs">
            <ScrollText className="w-6 h-6 text-[#5A6478] dark:text-[var(--text-3)]" aria-hidden="true" />
          </div>
          <p className="font-semibold text-[14px] text-[#14213D] dark:text-[var(--text-1)] mb-1">
            No document selected
          </p>
          <p className="text-[12.5px] text-[#5A6478] dark:text-[var(--text-2)] max-w-xs leading-relaxed">
            Select any file from the queue to preview its contents
          </p>
        </div>
      </main>
    );
  }

  const currentPage = document.currentPage || 1;
  const totalPages = document.pages;

  return (
    <main 
      aria-label="Document preview" 
      className="lg:col-span-5 flex flex-col bg-[#FAF9F5] dark:bg-[var(--bg-surface)] rounded-xl border border-[#8A94A6]/30 dark:border-[var(--border)] overflow-hidden h-full transition-colors"
    >
      {/* Header - Clean file title */}
      <div className="h-12 px-4 border-b border-[#8A94A6]/25 dark:border-[var(--border)] flex items-center justify-between shrink-0 bg-[#FAF9F5] dark:bg-[var(--bg-surface)]">
        <div className="flex items-center gap-2 truncate">
          <h2 className="font-['IBM_Plex_Sans',sans-serif] text-[14px] font-semibold text-[#14213D] dark:text-[var(--text-1)] truncate" title={document.name}>
            {document.name}
          </h2>
        </div>
      </div>

      {/* Toolbar: Ghost utility style for frequent utilities (Previous/Next, zoom, Fit) */}
      <div className="h-11 px-3 border-b border-[#8A94A6]/25 dark:border-[var(--border)] flex items-center justify-between bg-white/70 dark:bg-[var(--bg-surface)]/90 backdrop-blur-sm shrink-0">
        {/* Pager utility */}
        <div className="flex items-center gap-1">
          <button 
            disabled={currentPage <= 1}
            onClick={() => onPageChange(Math.max(1, currentPage - 1))}
            className="h-7 px-2.5 rounded-md hover:bg-black/5 dark:bg-[var(--bg-elevated)] dark:border dark:border-[var(--border)] dark:hover:bg-[var(--bg-active)] disabled:opacity-30 disabled:hover:bg-transparent text-[#14213D] dark:text-[var(--text-1)] transition-colors active:scale-90 active:translate-y-px transition-all duration-100 ease-out flex items-center gap-1 text-[12.5px] font-medium cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none" 
            type="button" 
            aria-label="Previous"
          >
            <ChevronLeft className="w-4 h-4 leading-none" aria-hidden="true" />
            <span>Previous</span>
          </button>

          <span className="text-[12.5px] tabular-nums font-medium px-1.5 text-[#14213D] dark:text-[var(--text-1)] select-none" aria-live="polite">
            {currentPage} of {totalPages}
          </span>

          <button 
            disabled={currentPage >= totalPages}
            onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
            className="h-7 px-2.5 rounded-md hover:bg-black/5 dark:bg-[var(--bg-elevated)] dark:border dark:border-[var(--border)] dark:hover:bg-[var(--bg-active)] disabled:opacity-30 disabled:hover:bg-transparent text-[#14213D] dark:text-[var(--text-1)] transition-colors active:scale-90 active:translate-y-px transition-all duration-100 ease-out flex items-center gap-1 text-[12.5px] font-medium cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none" 
            type="button" 
            aria-label="Next"
          >
            <span>Next</span>
            <ChevronRight className="w-4 h-4 leading-none" aria-hidden="true" />
          </button>
        </div>

        {/* Zoom & Fit utilities (Ghost style) */}
        <div className="flex items-center gap-1">
          <div className="inline-flex items-center rounded-md p-0.5 bg-black/[0.03] dark:bg-[var(--bg-elevated)] border border-black/[0.06] dark:border-[var(--border)]">
            <button 
              onClick={handleZoomOut}
              className="w-7 h-7 rounded hover:bg-black/5 dark:hover:bg-[var(--bg-active)] text-[#14213D] dark:text-[var(--text-1)] transition-colors active:scale-90 active:translate-y-px transition-all duration-100 ease-out flex items-center justify-center cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none" 
              title="Zoom out" 
              aria-label="Zoom out" 
              type="button" 
            >
              <Minus className="w-4 h-4 leading-none" aria-hidden="true" />
            </button>
            <span className="text-[12px] tabular-nums font-medium text-[#14213D] dark:text-[var(--text-1)] px-1.5 min-w-[42px] text-center select-none" aria-label={`Current zoom level ${zoomLevel}%`}>
              {zoomLevel}%
            </span>
            <button 
              onClick={handleZoomIn}
              className="w-7 h-7 rounded hover:bg-black/5 dark:hover:bg-[var(--bg-active)] text-[#14213D] dark:text-[var(--text-1)] transition-colors active:scale-90 active:translate-y-px transition-all duration-100 ease-out flex items-center justify-center cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none" 
              title="Zoom in" 
              aria-label="Zoom in" 
              type="button" 
            >
              <Plus className="w-4 h-4 leading-none" aria-hidden="true" />
            </button>
          </div>

          <div className="w-px h-3.5 bg-black/10 dark:bg-[var(--border)] mx-0.5" />

          <button 
            onClick={handleZoomReset}
            className="h-7 px-2.5 rounded-md hover:bg-black/5 dark:bg-[var(--bg-elevated)] dark:border dark:border-[var(--border)] dark:hover:bg-[var(--bg-active)] text-[#14213D] dark:text-[var(--text-1)] transition-colors active:scale-90 active:translate-y-px transition-all duration-100 ease-out flex items-center gap-1 text-[12.5px] font-medium cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none" 
            title="Fit" 
            aria-label="Fit" 
            type="button" 
          >
            <Maximize2 className="w-3.5 h-3.5 leading-none" aria-hidden="true" />
            <span>Fit</span>
          </button>
        </div>
      </div>

      {/* Document Viewport / Canvas */}
      <div className="flex-1 bg-[#EAE8E1]/60 dark:bg-[var(--bg-base)] p-4 overflow-y-auto flex justify-center items-start transition-colors">
        <div 
          style={{ transform: `scale(${zoomLevel / 100})`, transformOrigin: 'top center' }}
          className="transition-transform duration-150 w-full flex justify-center"
        >
          {document.previewImageUrl ? (
            <div className="w-full max-w-[560px] bg-white dark:bg-[var(--paper-bg)] border border-[#14213D]/12 dark:border-[var(--paper-border)] rounded-[4px] shadow-[0_4px_16px_rgba(20,33,61,0.07)] dark:shadow-[0_4px_24px_rgba(0,0,0,0.5)] p-3 flex justify-center">
              <img 
                src={document.previewImageUrl} 
                alt={`${document.name} page ${currentPage}`}
                className="max-w-full h-auto object-contain rounded"
              />
            </div>
          ) : (
            <div 
              role="region" 
              aria-label={`Document preview: ${document.name}, page ${currentPage} of ${totalPages}`}
              className="w-full max-w-[480px] bg-[#FCFBF8] dark:bg-[var(--paper-bg)] border border-[#14213D]/12 dark:border-[var(--paper-border)] rounded-[2px] shadow-[0_4px_16px_rgba(20,33,61,0.07),0_1px_3px_rgba(20,33,61,0.05)] dark:shadow-[0_4px_24px_rgba(0,0,0,0.5),0_1px_4px_rgba(0,0,0,0.3)] p-6 text-[#1A1A1A] dark:text-[var(--paper-text)] relative select-text transition-colors"
            >
              <div className="border-b-2 border-black/80 pb-3 mb-4 flex justify-between items-start">
                <div>
                  <p className="text-[10px] tracking-widest text-[#374151] dark:text-[var(--text-3)] uppercase font-mono font-medium">
                    DOCUMENT PREVIEW
                  </p>
                  <h3 className="font-['IBM_Plex_Serif',serif] text-[15px] font-bold text-[#1A1A1A] dark:text-[var(--paper-text)] uppercase truncate max-w-[320px]">
                    {document.name}
                  </h3>
                </div>
                <span className="text-[11px] font-mono text-[#4B5563] dark:text-[var(--text-3)]">
                  Page {currentPage} of {totalPages}
                </span>
              </div>

              <div className="text-[12px] font-['IBM_Plex_Serif',serif] leading-relaxed text-[#2D3139] dark:text-[var(--paper-text)] space-y-3">
                <p className="italic text-[#4B5563] dark:text-[var(--text-3)]">
                  [Document preview raster unavailable. Extracted text is displayed in the right panel.]
                </p>
                {document.extractedText ? (
                  <div className="p-3 bg-[#F4F2EC] dark:bg-[var(--bg-base)] rounded border border-black/10 dark:border-[var(--border)] font-mono text-[11px] text-[#1A1A1A] dark:text-[var(--text-1)] whitespace-pre-wrap max-h-60 overflow-y-auto">
                    {document.extractedText.slice(0, 320)}...
                  </div>
                ) : (
                  <div className="p-4 bg-black/[0.02] dark:bg-white/[0.02] rounded border border-dashed border-[#8A94A6] dark:border-[var(--border)] text-center text-[#5A6478] dark:text-[var(--text-3)] text-[12px]">
                    Document has not been extracted yet.
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </main>
  );
};
