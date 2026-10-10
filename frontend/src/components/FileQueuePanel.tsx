import React, { useRef } from 'react';
import { Upload, PlusCircle } from 'lucide-react';
import { DocumentItem } from '../types';

interface FileQueuePanelProps {
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
          >
            {documents.length} {documents.length === 1 ? 'file' : 'files'}
          </span>
          {!isEmpty && (
            <button
              onClick={onClearFinished}
              disabled={!hasFinished}
              className={`text-[12px] font-medium transition-all duration-150 px-2 py-0.5 rounded ${
                hasFinished
                  ? 'text-[#4B5563] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)] hover:bg-black/[0.04] dark:bg-[var(--bg-elevated)] dark:border dark:border-[var(--border)] hover:dark:bg-[var(--bg-active)] cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none'
                  : 'text-[#8A94A6] dark:text-[var(--text-3)] opacity-40 cursor-not-allowed select-none'
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
            className="flex-1 border-2 border-dashed border-[#8A94A6]/40 dark:border-[var(--border)] hover:border-[#0F766E]/70 dark:hover:border-[var(--accent)]/50 bg-white/40 dark:bg-[var(--bg-elevated)]/40 hover:bg-[#0F766E]/[0.02] dark:hover:bg-[var(--bg-elevated)]/70 rounded-lg transition-colors p-4 text-center cursor-pointer flex flex-col items-center justify-center"
          >
            <input 
              ref={fileInputRef}
              type="file" 
              className="sr-only" 
              multiple 
              accept=".pdf,.tiff,.tif,.jpg,.jpeg,.png" 
              onChange={handleFileChange}
            />
            <div className="w-10 h-10 rounded-lg bg-black/[0.04] dark:bg-[var(--bg-elevated)] dark:border dark:border-[var(--border)] flex items-center justify-center mb-3 text-[#14213D] dark:text-[var(--text-1)]">
              <Upload className="w-5 h-5 text-[#14213D] dark:text-[var(--text-1)]" aria-hidden="true" />
            </div>
            <p className="font-semibold text-[14px] text-[#14213D] dark:text-[var(--text-1)] mb-1">
              Drop PDF or image files here
            </p>
            <p className="text-[12px] text-[#5A6478] dark:text-[var(--text-2)] mb-4">
              Supports PDF, PNG, JPG, TIFF
            </p>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                fileInputRef.current?.click();
              }}
              className="h-8 px-3.5 rounded-lg border border-[#8A94A6] dark:border-[var(--border)] hover:border-[#14213D] dark:hover:border-[var(--border-strong)] bg-white dark:bg-[var(--bg-elevated)] text-[#14213D] dark:text-[var(--text-1)] text-[13px] font-medium transition-all duration-150 ease-out hover:bg-black/[0.02] hover:dark:bg-[var(--bg-active)] hover:scale-[1.02] hover:shadow-xs active:scale-[0.98] cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none"
            >
              Browse files
            </button>
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
              className="border-2 border-dashed border-[#8A94A6]/40 dark:border-[var(--border)] hover:border-[#0F766E]/70 dark:hover:border-[var(--accent)]/50 bg-white/40 dark:bg-[var(--bg-elevated)]/40 hover:bg-[#0F766E]/[0.02] dark:hover:bg-[var(--bg-elevated)]/70 rounded-lg transition-colors p-3 text-center cursor-pointer group flex flex-col items-center justify-center focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none"
              tabIndex={0}
              role="button"
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
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
            role="listbox" 
            aria-label="Document queue list"
          >
            {documents.map((doc) => {
              const isSelected = doc.id === selectedDocId;

              // Status badges with Pro Dark tokens
              let statusBadgeClass = 'bg-slate-100 dark:bg-[var(--bg-elevated)] text-slate-800 dark:text-[var(--text-2)] border border-slate-200 dark:border-[var(--border)]';
              let statusLabel: string = doc.status;

              if (doc.status === 'Done') {
                statusBadgeClass = 'bg-emerald-50 dark:bg-[var(--success)]/12 text-emerald-800 dark:text-[var(--success)] border border-emerald-200/90 dark:border-[var(--success)]/25';
                statusLabel = `Done · ${doc.pages} ${doc.pages === 1 ? 'page' : 'pages'}`;
              } else if (doc.status === 'Processing') {
                statusBadgeClass = 'bg-teal-50 dark:bg-[var(--accent)]/12 text-teal-700 dark:text-[var(--accent)] border border-teal-200 dark:border-[var(--accent)]/25';
                statusLabel = `Processing ${doc.processedPages || 1} of ${doc.pages} pages`;
              } else if (doc.status === 'Waiting') {
                statusBadgeClass = 'bg-slate-100 dark:bg-[var(--bg-elevated)] text-slate-800 dark:text-[var(--text-2)] border border-slate-200 dark:border-[var(--border)]';
                statusLabel = `Queued #${doc.queuePosition || 1}`;
              } else if (doc.status === 'Failed') {
                statusBadgeClass = 'bg-red-50 dark:bg-[var(--danger)]/12 text-red-700 dark:text-[var(--danger)] border border-red-200 dark:border-[var(--danger)]/25';
                statusLabel = 'Failed';
              } else if (doc.status === 'Truncated') {
                statusBadgeClass = 'bg-amber-50 dark:bg-[var(--warning)]/12 text-amber-800 dark:text-[var(--warning)] border border-amber-200 dark:border-[var(--warning)]/25';
                statusLabel = `Truncated · ${doc.pages} ${doc.pages === 1 ? 'page' : 'pages'}`;
              } else if (doc.status === 'Not extracted') {
                statusBadgeClass = 'bg-slate-100 dark:bg-[var(--bg-elevated)] text-slate-700 dark:text-[var(--text-2)] border border-slate-200 dark:border-[var(--border)]';
                statusLabel = 'Not extracted';
              }

              const progressPercent = doc.pages > 0 && doc.processedPages
                ? Math.round((doc.processedPages / doc.pages) * 100)
                : 0;

              return (
                <div 
                  key={doc.id}
                  role="option" 
                  aria-selected={isSelected} 
                  tabIndex={0} 
                  onClick={() => onSelectDoc(doc.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      onSelectDoc(doc.id);
                    }
                  }}
                  className={`p-3 rounded-lg cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:ring-offset-1 transition-colors duration-150 ${
                    isSelected
                      ? 'bg-[#0F766E]/[0.08] dark:bg-[var(--accent)]/[0.08] ring-1 ring-teal-700/40 dark:ring-[var(--accent)]/30 hover:bg-[#0F766E]/[0.12] dark:hover:bg-[var(--accent)]/[0.12]'
                      : 'hover:bg-black/[0.04] dark:hover:bg-[var(--bg-elevated)]'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span 
                      className={`text-[13.5px] truncate font-medium text-[#14213D] dark:text-[var(--text-1)] ${isSelected ? 'font-semibold' : ''}`}
                      title={doc.name}
                    >
                      {doc.name}
                    </span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className={`inline-flex items-center text-[11.5px] font-medium px-2 py-0.5 rounded shrink-0 ${statusBadgeClass}`}>
                        {statusLabel}
                      </span>
                      {doc.isReExtractionQueued && (
                        <span className="inline-flex items-center text-[11px] font-medium px-1.5 py-0.5 rounded bg-amber-500/10 dark:bg-[var(--warning)]/10 text-amber-800 dark:text-[var(--warning)] border border-amber-500/20 dark:border-[var(--warning)]/30 shrink-0">
                          Queued #{doc.queuePosition || 1}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Metadata and Progress */}
                  <div className="flex items-center justify-between text-[#5A6478] dark:text-[var(--text-2)] text-[12px] tabular-nums mt-0.5">
                    <span>
                      {doc.pages} {doc.pages === 1 ? 'page' : 'pages'} {doc.size ? `· ${doc.size}` : ''}
                    </span>

                    {/* Progress tracking distinct from preview page */}
                    {doc.status === 'Processing' && (
                      <span className="text-[#0F766E] dark:text-[var(--accent)] font-medium text-[11.5px]">
                        Processing {doc.processedPages || 0} of {doc.pages} pages
                      </span>
                    )}
                    {doc.status === 'Waiting' && (
                      <div className="flex items-center gap-1.5">
                        <span className="text-[#5A6478] dark:text-[var(--text-2)] font-medium text-[11.5px]">
                          {doc.statusNote || `Queued #${doc.queuePosition || 1}`}
                        </span>
                        {onRemoveFromQueue && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              onRemoveFromQueue(doc.id);
                            }}
                            className="text-[#5A6478] dark:text-[var(--text-2)] hover:text-red-700 hover:dark:text-[var(--danger)] hover:bg-red-50 hover:dark:bg-[var(--danger)]/10 text-[11px] px-1.5 py-0.5 rounded transition-all duration-150 ease-out hover:scale-[1.05] active:scale-[0.95] cursor-pointer focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none"
                            title="Remove from queue"
                          >
                            Remove
                          </button>
                        )}
                      </div>
                    )}
                    {doc.isReExtractionQueued && (
                      <span className="text-amber-800 dark:text-[var(--warning)] font-medium text-[11.5px]">
                        Queued #{doc.queuePosition || 1}
                      </span>
                    )}
                  </div>

                  {/* Processing Row Progress Bar */}
                  {doc.status === 'Processing' && (
                    <div className="w-full h-1 bg-[#E2DFD7] dark:bg-[var(--accent-dim)] rounded-sm overflow-hidden mt-2">
                      <div 
                        className="h-full bg-[#0F766E] dark:bg-[var(--accent)] transition-all duration-300"
                        style={{ width: `${progressPercent}%` }}
                      />
                    </div>
                  )}

                  {/* Truncated Row */}
                  {doc.status === 'Truncated' && doc.statusNote && (
                    <div className="mt-2 bg-[#B45309]/5 dark:bg-[var(--warning)]/10 p-2 rounded border border-[#B45309]/20 dark:border-[var(--warning)]/30 text-[12px] text-[#78350f] dark:text-[var(--warning)]">
                      <p className="leading-snug break-words">
                        {doc.statusNote}
                      </p>
                      <div className="mt-2 flex justify-end">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onOpenSettings();
                          }}
                          className="px-2 py-0.5 rounded border border-[#B45309]/40 dark:border-[var(--border)] bg-white dark:bg-[var(--bg-elevated)] hover:bg-[#B45309]/15 hover:dark:bg-[var(--bg-active)] text-[11.5px] font-medium text-[#78350f] dark:text-[var(--warning)] transition-all duration-150 ease-out hover:scale-[1.03] hover:shadow-xs active:scale-[0.97] cursor-pointer focus-visible:ring-2 focus-visible:ring-[#B45309] focus-visible:outline-none"
                        >
                          Open settings
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Failed Row */}
                  {doc.status === 'Failed' && doc.statusNote && (
                    <div className="mt-2 bg-red-50 dark:bg-[var(--danger)]/10 p-2 rounded border border-red-200 dark:border-[var(--danger)]/30 text-[12px] text-[#B91C1C] dark:text-[var(--danger)]">
                      <p className="leading-snug break-words">
                        {doc.statusNote}
                      </p>
                      <div className="mt-2 flex justify-end gap-2">
                        {onRetryDoc && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              onRetryDoc(doc.id);
                            }}
                            className="px-2 py-0.5 rounded border border-red-300 dark:border-[var(--border)] bg-white dark:bg-[var(--bg-elevated)] hover:bg-red-50 hover:dark:bg-[var(--bg-active)] text-[11.5px] font-medium text-[#B91C1C] dark:text-[var(--danger)] transition-all duration-150 ease-out hover:scale-[1.03] hover:shadow-xs active:scale-[0.97] cursor-pointer focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none"
                          >
                            Retry
                          </button>
                        )}
                        {onRemoveDoc && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              onRemoveDoc(doc.id);
                            }}
                            className="px-2 py-0.5 rounded border border-red-300 dark:border-[var(--border)] bg-white dark:bg-[var(--bg-elevated)] hover:bg-red-50 hover:dark:bg-[var(--bg-active)] text-[11.5px] font-medium text-[#B91C1C] dark:text-[var(--danger)] transition-all duration-150 ease-out hover:scale-[1.03] hover:shadow-xs active:scale-[0.97] cursor-pointer focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none"
                          >
                            Remove
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </aside>
  );
};
