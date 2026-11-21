import React, { useRef } from 'react';
import { Upload, PlusCircle } from 'lucide-react';
import { DocumentItem } from '../../types';
import { QueueItemRow } from './QueueItemRow';

export interface FileQueuePanelProps {
  documents: DocumentItem[];
  selectedDocId: string | null;
  onSelectDoc: (id: string) => void;
  onAddFiles: (files: FileList | File[]) => void;
  onClearFinished: () => void;
  onOpenSettings: () => void;
  onRetryDoc?: (id: string) => void;
  onRemoveDoc?: (id: string) => void;
  onRemoveFromQueue?: (id: string) => void;
}

export const FileQueuePanel: React.FC<FileQueuePanelProps> = ({
  documents,
  selectedDocId,
  onSelectDoc,
  onAddFiles,
  onClearFinished,
  onOpenSettings,
  onRetryDoc,
  onRemoveDoc,
  onRemoveFromQueue,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      onAddFiles(e.target.files);
      e.target.value = '';
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      onAddFiles(e.dataTransfer.files);
    }
  };

  const isEmpty = documents.length === 0;
  const finishedCount = documents.filter((d) => d.status === 'Done' || d.status === 'Failed').length;
  const hasFinished = finishedCount > 0;

  return (
    <div 
      className="flex flex-col bg-[#272727] dark:bg-[var(--bg-surface)] overflow-hidden h-full transition-colors"
    >
      {/* Pane Header */}
      <div className="h-12 px-4 border-b border-white/8 dark:border-[var(--border)] flex items-center justify-between shrink-0 bg-[#272727] dark:bg-[var(--bg-surface)]">
        <div className="flex items-center gap-2">
          <h2 className="text-[14px] font-semibold text-[#F3F3F3] dark:text-[var(--text-1)]">
            File Queue
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <span 
            className="text-[12px] font-medium tabular-nums text-[#A6A6A6] dark:text-[var(--text-2)] px-2 py-0.5 rounded-sm bg-white/[0.04] border border-white/8" 
            aria-label={`${documents.length} files in queue`}
            aria-live="polite"
          >
            {documents.length} {documents.length === 1 ? 'file' : 'files'}
          </span>
          {!isEmpty && (
            <button
              onClick={onClearFinished}
              disabled={!hasFinished}
              className={`text-[12px] font-medium transition-all duration-150 px-2 py-0.5 rounded-sm min-h-[24px] min-w-[24px] inline-flex items-center justify-center ${
                hasFinished
                  ? 'text-[#A6A6A6] hover:text-[#F3F3F3] bg-white/[0.04] hover:bg-white/[0.08] border border-white/8 cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none'
                  : 'text-[#929292] opacity-40 cursor-not-allowed select-none'
              }`}
              title={hasFinished ? `Purge ${finishedCount} completed/failed items from queue` : 'No finished items to clear'}
            >
              Clear Finished
            </button>
          )}
        </div>
      </div>

      {/* When Empty: Refined Dropzone */}
      {isEmpty ? (
        <div className="flex-1 p-4 flex flex-col">
          <div
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className="flex-1 border-2 border-dashed border-white/10 hover:border-[#60CDFF]/50 bg-white/[0.02] hover:bg-[#60CDFF]/[0.03] rounded-sm transition-colors p-4 text-center cursor-pointer flex flex-col items-center justify-center focus-within:ring-2 focus-within:ring-[#60CDFF]"
          >
            <input 
              ref={fileInputRef}
              type="file" 
              className="sr-only" 
              multiple
              accept=".pdf,.tiff,.tif,.jpg,.jpeg,.png" 
              onChange={handleFileChange}
              aria-label="Upload documents"
            />
            <div className="w-10 h-10 rounded-full bg-[#60CDFF]/15 flex items-center justify-center mb-3 text-[#60CDFF]">
              <Upload className="w-5 h-5 text-[#60CDFF]" aria-hidden="true" />
            </div>
            <p className="font-semibold text-[13.5px] text-[#F3F3F3] dark:text-[var(--text-1)] mb-1">
              Add Documents
            </p>
            <p className="text-[12px] font-medium text-[#A6A6A6] dark:text-[var(--text-2)] max-w-[200px] leading-relaxed">
              Drag & drop archival files here or click to browse
            </p>
            <span className="text-[11px] text-[#A6A6A6] dark:text-[var(--text-2)] mt-2 font-mono">
              PDF, TIFF, JPG, PNG
            </span>
          </div>
        </div>
      ) : (
        <>
          {/* Compact Drop Zone */}
          <div className="p-3 border-b border-white/8 dark:border-[var(--border)] shrink-0">
            <div 
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className="border-2 border-dashed border-white/10 hover:border-[#60CDFF]/50 bg-white/[0.02] hover:bg-[#60CDFF]/[0.03] rounded-sm transition-colors p-3 text-center cursor-pointer group flex flex-col items-center justify-center focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
              tabIndex={0}
              role="button"
              aria-label="Upload documents"
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  fileInputRef.current?.click();
                }
              }}
            >
              <input 
                ref={fileInputRef}
                type="file" 
                className="sr-only" 
                multiple
                accept=".pdf,.tiff,.tif,.jpg,.jpeg,.png" 
                onChange={handleFileChange}
                aria-label="Upload document files"
              />
              <div className="flex items-center justify-center gap-1.5 text-[#F3F3F3]">
                <PlusCircle className="w-4 h-4 text-[#60CDFF]" aria-hidden="true" />
                <span className="font-semibold text-[13px] text-[#F3F3F3] dark:text-[var(--text-1)]">
                  Drop PDF or image files here
                </span>
              </div>
              <p className="text-[12px] font-medium text-[#A6A6A6] dark:text-[var(--text-2)]">
                Supports PDF, PNG, JPG, TIFF
              </p>
            </div>
          </div>

          {/* Document list */}
          <div 
            className="flex-1 overflow-y-auto p-2 space-y-1.5" 
            role="list" 
            aria-label="Document queue list"
          >
            {documents.map((doc) => (
              <QueueItemRow
                key={doc.id}
                doc={doc}
                isSelected={doc.id === selectedDocId}
                onSelectDoc={onSelectDoc}
                onOpenSettings={onOpenSettings}
                onRetryDoc={onRetryDoc}
                onRemoveDoc={onRemoveDoc}
                onRemoveFromQueue={onRemoveFromQueue}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
};
