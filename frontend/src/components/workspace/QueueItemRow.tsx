import React from 'react';
import { DocumentItem } from '../../types';

export interface QueueItemRowProps {
  doc: DocumentItem;
  isSelected: boolean;
  onSelectDoc: (id: string) => void;
  onOpenSettings: () => void;
  onRetryDoc?: (id: string) => void;
  onRemoveDoc?: (id: string) => void;
  onRemoveFromQueue?: (id: string) => void;
}

export const QueueItemRow: React.FC<QueueItemRowProps> = ({
  doc,
  isSelected,
  onSelectDoc,
  onOpenSettings,
  onRetryDoc,
  onRemoveDoc,
  onRemoveFromQueue,
}) => {
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
      role="listitem" 
      aria-current={isSelected ? 'true' : undefined} 
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
                className="text-[#5A6478] dark:text-[var(--text-2)] hover:text-red-700 hover:dark:text-[var(--danger)] hover:bg-red-50 hover:dark:bg-[var(--danger)]/10 text-[11px] px-1.5 py-0.5 rounded min-h-[24px] min-w-[24px] inline-flex items-center justify-center transition-all duration-150 ease-out hover:scale-[1.05] active:scale-[0.95] cursor-pointer focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none"
                title="Cancel queued extraction"
                aria-label={`Cancel queued extraction for ${doc.name}`}
              >
                Cancel wait
              </button>
            )}
          </div>
        )}
        {doc.status !== 'Processing' && doc.status !== 'Waiting' && (onRemoveDoc || onRemoveFromQueue) && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              if (onRemoveDoc) {
                onRemoveDoc(doc.id);
              } else if (onRemoveFromQueue) {
                onRemoveFromQueue(doc.id);
              }
            }}
            className="text-[#5A6478] dark:text-[var(--text-2)] hover:text-red-700 hover:dark:text-[var(--danger)] hover:bg-red-50 hover:dark:bg-[var(--danger)]/10 text-[11px] px-1.5 py-0.5 rounded min-h-[24px] min-w-[24px] inline-flex items-center justify-center transition-all duration-150 ease-out hover:scale-[1.05] active:scale-[0.95] cursor-pointer focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none"
            title="Remove file"
            aria-label={`Remove ${doc.name}`}
          >
            Remove
          </button>
        )}
        {doc.isReExtractionQueued && (
          <span className="text-amber-800 dark:text-[var(--warning)] font-medium text-[11.5px]">
            Queued #{doc.queuePosition || 1}
          </span>
        )}
      </div>

      {/* Processing Row Progress Bar */}
      {doc.status === 'Processing' && (
        <div className="w-full h-1 bg-[#E2DFD7] dark:bg-[var(--accent-dim)] rounded-sm overflow-hidden mt-2 relative">
          <div 
            className="h-full bg-[#0F766E] dark:bg-[var(--accent)] transition-all duration-300 relative overflow-hidden"
            style={{ width: `${progressPercent}%` }}
          >
            <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/40 dark:via-white/30 to-transparent animate-shimmer" />
          </div>
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
              className="px-2 py-0.5 rounded border border-[#B45309]/40 dark:border-[var(--border)] bg-white dark:bg-[var(--bg-elevated)] hover:bg-[#B45309]/15 hover:dark:bg-[var(--bg-active)] text-[11.5px] font-medium text-[#78350f] dark:text-[var(--warning)] min-h-[24px] min-w-[24px] inline-flex items-center justify-center transition-all duration-150 ease-out hover:scale-[1.03] hover:shadow-xs active:scale-[0.97] cursor-pointer focus-visible:ring-2 focus-visible:ring-[#B45309] focus-visible:outline-none"
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
                className="px-2 py-0.5 rounded border border-red-300 dark:border-[var(--border)] bg-white dark:bg-[var(--bg-elevated)] hover:bg-red-50 hover:dark:bg-[var(--bg-active)] text-[11.5px] font-medium text-[#B91C1C] dark:text-[var(--danger)] min-h-[24px] min-w-[24px] inline-flex items-center justify-center transition-all duration-150 ease-out hover:scale-[1.03] hover:shadow-xs active:scale-[0.97] cursor-pointer focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none"
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
                className="px-2 py-0.5 rounded border border-red-300 dark:border-[var(--border)] bg-white dark:bg-[var(--bg-elevated)] hover:bg-red-50 hover:dark:bg-[var(--bg-active)] text-[11.5px] font-medium text-[#B91C1C] dark:text-[var(--danger)] min-h-[24px] min-w-[24px] inline-flex items-center justify-center transition-all duration-150 ease-out hover:scale-[1.03] hover:shadow-xs active:scale-[0.97] cursor-pointer focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none"
              >
                Remove
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
