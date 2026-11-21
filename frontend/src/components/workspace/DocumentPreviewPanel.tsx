import React, { useState, useEffect } from 'react';
import { ScrollText, ChevronLeft, ChevronRight, Minus, Plus, Maximize2 } from 'lucide-react';
import { DocumentItem } from '../../types';

export interface DocumentPreviewPanelProps {
  document: DocumentItem | null;
  onPageChange: (newPage: number) => void;
}

export const DocumentPreviewPanel: React.FC<DocumentPreviewPanelProps> = ({
  document,
  onPageChange,
}) => {
  const [zoomLevel, setZoomLevel] = useState<number>(100);
  const [imageLoadError, setImageLoadError] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);

  useEffect(() => {
    setImageLoadError(false);
    setImageLoaded(false);
  }, [document?.id, document?.currentPage, document?.previewImageUrl]);

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
      <section 
        aria-label="Document preview empty" 
        className="flex flex-col bg-[#272727] dark:bg-[var(--bg-surface)] overflow-hidden h-full transition-colors"
      >
        <div className="h-12 px-4 border-b border-white/8 dark:border-[var(--border)] flex items-center justify-between shrink-0 bg-[#272727] dark:bg-[var(--bg-surface)]">
          <h2 className="text-[14px] font-semibold text-[#F3F3F3] dark:text-[var(--text-1)]">
            Document Preview
          </h2>
        </div>
        <div className="h-11 px-3 border-b border-white/8 dark:border-[var(--border)] flex items-center justify-between bg-white/[0.02] dark:bg-[var(--bg-surface)] shrink-0 text-[#A6A6A6] text-[13px] select-none">
          <div className="flex items-center gap-1 opacity-50">
            <span className="h-7 px-2 flex items-center gap-1 font-medium text-[12.5px]">Previous</span>
            <span className="px-2 text-[12.5px] tabular-nums">0 of 0</span>
            <span className="h-7 px-2 flex items-center gap-1 font-medium text-[12.5px]">Next</span>
          </div>
          <div className="flex items-center gap-1 opacity-50">
            <span className="h-7 px-2 flex items-center font-medium text-[12.5px]">Fit</span>
          </div>
        </div>
        <div className="flex-1 bg-[#181818] dark:bg-[var(--canvas-matte)] p-6 flex flex-col items-center justify-center text-center select-none">
          <div className="w-12 h-12 rounded-full bg-white/[0.04] border border-white/8 flex items-center justify-center mb-3 text-[#A6A6A6]">
            <ScrollText className="w-6 h-6 text-[#A6A6A6]" aria-hidden="true" />
          </div>
          <p className="font-semibold text-[14px] text-[#F3F3F3] dark:text-[var(--text-1)] mb-1">
            No document selected
          </p>
          <p className="text-[12.5px] text-[#A6A6A6] dark:text-[var(--text-2)] max-w-xs leading-relaxed">
            Select any file from the queue to preview its contents
          </p>
        </div>
      </section>
    );
  }

  const currentPage = document.currentPage || 1;
  const totalPages = document.pages;

  return (
    <section 
      aria-label="Document preview" 
      className="flex flex-col bg-[#272727] dark:bg-[var(--bg-surface)] overflow-hidden h-full transition-colors"
    >
      {/* Header - Clean file title */}
      <div className="h-12 px-4 border-b border-white/8 dark:border-[var(--border)] flex items-center justify-between shrink-0 bg-[#272727] dark:bg-[var(--bg-surface)]">
        <div className="flex items-center gap-2 truncate">
          <h2 className="text-[14px] font-semibold text-[#F3F3F3] dark:text-[var(--text-1)] truncate" title={document.name}>
            {document.name}
          </h2>
        </div>
      </div>

      {/* Toolbar: Ghost utility style for frequent utilities (Previous/Next, zoom, Fit) */}
      <div className="h-11 px-3 border-b border-white/8 dark:border-[var(--border)] flex items-center justify-between bg-white/[0.02] dark:bg-[var(--bg-surface)] shrink-0">
        {/* Pager utility */}
        <div className="flex items-center gap-1">
          <button 
            disabled={currentPage <= 1}
            onClick={() => onPageChange(Math.max(1, currentPage - 1))}
            className="h-7 px-2.5 rounded-sm hover:bg-white/[0.08] hover:text-[#F3F3F3] disabled:opacity-30 disabled:hover:bg-transparent text-[#A6A6A6] active:scale-[0.96] transition-all duration-100 ease-tactile flex items-center gap-1 text-[12.5px] font-medium cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none" 
            type="button" 
            aria-label="Previous"
          >
            <ChevronLeft className="w-4 h-4 leading-none" aria-hidden="true" />
            <span>Previous</span>
          </button>

          <span className="text-[12.5px] tabular-nums font-medium px-1.5 text-[#F3F3F3] select-none" aria-live="polite">
            {currentPage} of {totalPages}
          </span>

          <button 
            disabled={currentPage >= totalPages}
            onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
            className="h-7 px-2.5 rounded-sm hover:bg-white/[0.08] hover:text-[#F3F3F3] disabled:opacity-30 disabled:hover:bg-transparent text-[#A6A6A6] active:scale-[0.96] transition-all duration-100 ease-tactile flex items-center gap-1 text-[12.5px] font-medium cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none" 
            type="button" 
            aria-label="Next"
          >
            <span>Next</span>
            <ChevronRight className="w-4 h-4 leading-none" aria-hidden="true" />
          </button>
        </div>

        {/* Zoom & Fit utilities */}
        <div className="flex items-center gap-1">
          <div className="inline-flex items-center rounded-sm p-0.5 bg-white/[0.04] border border-white/8">
            <button 
              onClick={handleZoomOut}
              className="w-7 h-7 rounded-sm hover:bg-white/[0.08] text-[#A6A6A6] hover:text-[#F3F3F3] active:scale-90 transition-all duration-100 ease-out flex items-center justify-center cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none" 
              title="Zoom out" 
              aria-label="Zoom out" 
              type="button" 
            >
              <Minus className="w-4 h-4 leading-none" aria-hidden="true" />
            </button>
            <span className="text-[12px] tabular-nums font-medium text-[#F3F3F3] px-1.5 min-w-[42px] text-center select-none" aria-label={`Current zoom level ${zoomLevel}%`}>
              {zoomLevel}%
            </span>
            <button 
              onClick={handleZoomIn}
              className="w-7 h-7 rounded-sm hover:bg-white/[0.08] text-[#A6A6A6] hover:text-[#F3F3F3] active:scale-90 transition-all duration-100 ease-out flex items-center justify-center cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none" 
              title="Zoom in" 
              aria-label="Zoom in" 
              type="button" 
            >
              <Plus className="w-4 h-4 leading-none" aria-hidden="true" />
            </button>
          </div>

          <div className="w-px h-3.5 bg-white/10 mx-0.5" />

          <button 
            onClick={handleZoomReset}
            className="h-7 px-2.5 rounded-sm hover:bg-white/[0.08] text-[#A6A6A6] hover:text-[#F3F3F3] active:scale-90 transition-all duration-100 ease-out flex items-center gap-1 text-[12.5px] font-medium cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none" 
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
      <div className="flex-1 bg-[#181818] dark:bg-[var(--canvas-matte)] p-4 overflow-y-auto flex justify-center items-start transition-colors">
        <div 
          style={{ transform: `scale(${zoomLevel / 100})`, transformOrigin: 'top center' }}
          className="transition-transform duration-150 w-full flex justify-center"
        >
          {document.previewImageUrl && !imageLoadError ? (
            <div className="w-full max-w-[560px] bg-[#1e1e1e] dark:bg-[var(--paper-bg)] border border-white/10 dark:border-[var(--paper-border)] rounded-sm shadow-[0_4px_24px_rgba(0,0,0,0.5)] p-3 flex justify-center min-h-[300px] relative">
              {!imageLoaded && (
                <div className="absolute inset-3 bg-white/[0.04] rounded-sm flex items-center justify-center animate-pulse" aria-hidden="true">
                  <span className="text-2xs text-[#A6A6A6] font-mono">Rendering page...</span>
                </div>
              )}
              <img 
                src={document.previewImageUrl} 
                alt={`${document.name} page ${currentPage}`}
                className={`max-w-full h-auto object-contain rounded-sm transition-opacity duration-200 ease-tactile ${
                  imageLoaded ? 'opacity-100' : 'opacity-0'
                }`}
                onLoad={() => setImageLoaded(true)}
                onError={() => setImageLoadError(true)}
              />
            </div>
          ) : (
            <div 
              role="region" 
              aria-label={`Document preview: ${document.name}, page ${currentPage} of ${totalPages}`}
              className="w-full max-w-[480px] bg-[#1e1e1e] dark:bg-[var(--paper-bg)] border border-white/10 dark:border-[var(--paper-border)] rounded-sm shadow-[0_4px_24px_rgba(0,0,0,0.5)] p-6 text-[#F3F3F3] dark:text-[var(--paper-text)] relative select-text transition-colors"
            >
              <div className="border-b-2 border-white/20 pb-3 mb-4 flex justify-between items-start">
                <div>
                  <p className="text-[10px] tracking-widest text-[#A6A6A6] uppercase font-mono font-medium">
                    DOCUMENT PREVIEW
                  </p>
                  <h3 className="font-['IBM_Plex_Serif',serif] text-[15px] font-bold text-[#F3F3F3] uppercase truncate max-w-[320px]">
                    {document.name}
                  </h3>
                </div>
                <span className="text-[11px] font-mono text-[#A6A6A6]">
                  Page {currentPage} of {totalPages}
                </span>
              </div>

              <div className="text-[12px] font-['IBM_Plex_Serif',serif] leading-relaxed text-[#D4D4D4] space-y-3">
                <p className="italic text-[#A6A6A6]">
                  {imageLoadError 
                    ? '[Raster preview could not be loaded from backend. Extracted text is displayed in the right panel.]'
                    : '[Document preview raster unavailable. Extracted text is displayed in the right panel.]'}
                </p>
                {document.extractedText ? (
                  <div className="p-3 bg-black/20 rounded-sm border border-white/10 font-mono text-[11px] text-[#F3F3F3] whitespace-pre-wrap max-h-60 overflow-y-auto">
                    {document.extractedText.slice(0, 320)}...
                  </div>
                ) : (
                  <div className="p-4 bg-white/[0.02] rounded-sm border border-dashed border-white/15 text-center text-[#A6A6A6] text-[12px]">
                    Document has not been extracted yet.
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
};
