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
    <aside 
      aria-label="Document queue" 
      className="lg:col-span-3 flex flex-col bg-[#FBF9F4] dark:bg-[var(--bg-surface)] rounded-xl border border-[#8A94A6]/30 dark:border-[var(--border)] overflow-hidden h-full transition-colors"
    >
      {/* Pane Header */}
      <div className="h-12 px-4 border-b border-[#8A94A6]/25 dark:border-[var(--border)] flex items-center justify-between shrink-0 bg-[#FBF9F4] dark:bg-[var(--bg-surface)]">
        <div className="flex items-center gap-2">
          <h2 className="font-['IBM_Plex_Sans',sans-serif] text-[14px] font-semibold text-[#14213D] dark:text-[var(--text-1)]">
            File Queue
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <span 
            className="text-[12px] font-medium tabular-nums text-[#374151] dark:text-[var(--text-2)] px-2 py-0.5 rounded-md bg-black/[0.04] dark:bg-[var(--bg-elevated)] dark:border dark:border-[var(--border)]" 
            aria-label={`${documents.length} files in queue`}
            aria-live="polite"
          >
            {documents.length} {documents.length === 1 ? 'file' : 'files'}
          </span>
          {!isEmpty && (
            <button
              onClick={onClearFinished}
              disabled={!hasFinished}
              className={`text-[12px] font-medium transition-all duration-150 px-2 py-0.5 rounded min-h-[24px] min-w-[24px] inline-flex items-center justify-center ${
                hasFinished
                  ? 'text-[#4B5563] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)] hover:bg-black/[0.04] dark:bg-[var(--bg-elevated)] dark:border dark:border-[var(--border)] hover:dark:bg-[var(--bg-active)] cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none'
                  : 'text-[#5A6478] dark:text-[var(--text-3)] opacity-40 cursor-not-allowed select-none'
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
            className="flex-1 border-2 border-dashed border-[#8A94A6]/40 dark:border-[var(--border)] hover:border-[#0F766E]/70 dark:hover:border-[var(--accent)]/50 bg-white/40 dark:bg-[var(--bg-elevated)]/40 hover:bg-[#0F766E]/[0.02] dark:hover:bg-[var(--bg-elevated)]/70 rounded-lg transition-colors p-4 text-center cursor-pointer flex flex-col items-center justify-center focus-within:ring-2 focus-within:ring-[#0F766E]"
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
            <div className="w-10 h-10 rounded-full bg-[#0F766E]/10 dark:bg-[var(--accent)]/15 flex items-center justify-center mb-3 text-[#0F766E] dark:text-[var(--accent)]">
              <Upload className="w-5 h-5" aria-hidden="true" />
            </div>
            <p className="font-semibold text-[13.5px] text-[#14213D] dark:text-[var(--text-1)] mb-1">
              Add Documents
            </p>
            <p className="text-[12px] font-medium text-[#5A6478] dark:text-[var(--text-2)] max-w-[200px] leading-relaxed">
              Drag & drop archival files here or click to browse
            </p>
            <span className="text-[11px] text-[#5A6478] dark:text-[var(--text-2)] mt-2 font-mono">
              PDF, TIFF, JPG, PNG
            </span>
          </div>
        </div>
      ) : (
        <>
          {/* Compact Drop Zone */}
          <div className="p-3 border-b border-[#8A94A6]/25 dark:border-[var(--border)] shrink-0">
            <div 
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className="border-2 border-dashed border-[#8A94A6]/40 dark:border-[var(--border)] hover:border-[#0F766E]/70 dark:hover:border-[var(--accent)]/50 bg-white/40 dark:bg-[var(--bg-elevated)]/40 hover:bg-[#0F766E]/[0.02] dark:hover:bg-[var(--bg-elevated)]/70 rounded-lg transition-colors p-3 text-center cursor-pointer group flex flex-col items-center justify-center focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] focus-visible:outline-none"
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
              <div className="flex items-center justify-center gap-1.5 text-[#14213D] dark:text-[var(--text-1)]">
                <PlusCircle className="w-4 h-4 text-[#0F766E] dark:text-[var(--accent)]" aria-hidden="true" />
                <span className="font-semibold text-[13px] text-[#14213D] dark:text-[var(--text-1)]">
                  Drop PDF or image files here
                </span>
              </div>
              <p className="text-[12px] font-medium text-[#5A6478] dark:text-[var(--text-2)]">
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
    </aside>
  );
};
