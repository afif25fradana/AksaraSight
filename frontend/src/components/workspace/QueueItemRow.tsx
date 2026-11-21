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
  let statusBadgeClass = 'bg-white/5 text-[#A6A6A6] border border-white/10';
  let statusLabel: string = doc.status;

  if (doc.status === 'Done') {
    statusBadgeClass = 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/25';
    statusLabel = `Done · ${doc.pages} ${doc.pages === 1 ? 'page' : 'pages'}`;
  } else if (doc.status === 'Processing') {
    statusBadgeClass = 'bg-[#60CDFF]/15 text-[#60CDFF] border border-[#60CDFF]/30';
    statusLabel = `Processing ${doc.processedPages || 1} of ${doc.pages} pages`;
  } else if (doc.status === 'Waiting') {
    statusBadgeClass = 'bg-white/5 text-[#A6A6A6] border border-white/10';
    statusLabel = `Queued #${doc.queuePosition || 1}`;
  } else if (doc.status === 'Failed') {
    statusBadgeClass = 'bg-red-500/15 text-red-400 border border-red-500/25';
    statusLabel = 'Failed';
  } else if (doc.status === 'Truncated') {
    statusBadgeClass = 'bg-amber-500/15 text-amber-400 border border-amber-500/25';
    statusLabel = `Truncated · ${doc.pages} ${doc.pages === 1 ? 'page' : 'pages'}`;
  } else if (doc.status === 'Not extracted') {
    statusBadgeClass = 'bg-white/5 text-[#A6A6A6] border border-white/10';
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
      className={`relative p-3 rounded-md cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:ring-offset-1 focus-visible:ring-offset-[#202020] transition-colors duration-150 ${
        isSelected
          ? 'bg-white/[0.08] text-[#F3F3F3]'
          : 'text-[#A6A6A6] hover:bg-white/[0.04] hover:text-[#F3F3F3]'
      }`}
    >
      {/* 3px vertical active indicator pill */}
      {isSelected && (
        <span
          className="w-[3px] h-4 rounded-full bg-[#60CDFF] absolute left-1 top-3"
          aria-hidden="true"
          data-testid="active-indicator"
        />
      )}

      <div className="flex items-center justify-between gap-2 mb-1">
        <span 
          className={`text-[13.5px] truncate font-medium text-[#F3F3F3] ${isSelected ? 'font-semibold' : ''}`}
          title={doc.name}
        >
          {doc.name}
        </span>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className={`inline-flex items-center text-[11.5px] font-medium px-2 py-0.5 rounded-sm shrink-0 ${statusBadgeClass}`}>
            {statusLabel}
          </span>
          {doc.isReExtractionQueued && (
            <span className="inline-flex items-center text-[11px] font-medium px-1.5 py-0.5 rounded-sm bg-amber-500/10 text-amber-400 border border-amber-500/20 shrink-0">
              Queued #{doc.queuePosition || 1}
            </span>
          )}
        </div>
      </div>

      {/* Metadata and Progress */}
      <div className="flex items-center justify-between text-[#A6A6A6] text-[12px] tabular-nums mt-0.5">
        <span>
          {doc.pages} {doc.pages === 1 ? 'page' : 'pages'} {doc.size ? `· ${doc.size}` : ''}
        </span>

        {/* Progress tracking distinct from preview page */}
        {doc.status === 'Processing' && (
          <span className="text-[#60CDFF] font-medium text-[11.5px]">
            Processing {doc.processedPages || 0} of {doc.pages} pages
          </span>
        )}
        {doc.status === 'Waiting' && (
          <div className="flex items-center gap-1.5">
            <span className="text-[#A6A6A6] font-medium text-[11.5px]">
              {doc.statusNote || `Queued #${doc.queuePosition || 1}`}
            </span>
            {onRemoveFromQueue && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onRemoveFromQueue(doc.id);
                }}
                className="text-[#A6A6A6] hover:text-red-400 hover:bg-red-500/10 text-[11px] px-1.5 py-0.5 rounded-md min-h-[24px] min-w-[24px] inline-flex items-center justify-center transition-all duration-150 ease-out cursor-pointer focus-visible:ring-2 focus-visible:ring-red-400 focus-visible:outline-none"
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
            className="text-[#A6A6A6] hover:text-red-400 hover:bg-red-500/10 text-[11px] px-1.5 py-0.5 rounded-md min-h-[24px] min-w-[24px] inline-flex items-center justify-center transition-all duration-150 ease-out cursor-pointer focus-visible:ring-2 focus-visible:ring-red-400 focus-visible:outline-none"
            title="Remove file"
            aria-label={`Remove ${doc.name}`}
          >
            Remove
          </button>
        )}
        {doc.isReExtractionQueued && (
          <span className="text-amber-400 font-medium text-[11.5px]">
            Queued #{doc.queuePosition || 1}
          </span>
        )}
      </div>

      {/* Processing Row Progress Bar */}
      {doc.status === 'Processing' && (
        <div className="w-full h-1 bg-white/10 rounded-full overflow-hidden mt-2 relative">
          <div 
            className="h-full bg-[#60CDFF] transition-all duration-300 relative overflow-hidden"
            style={{ width: `${progressPercent}%` }}
          >
            <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/40 to-transparent animate-shimmer" />
          </div>
        </div>
      )}

      {/* Truncated Row */}
      {doc.status === 'Truncated' && doc.statusNote && (
        <div className="mt-2 bg-amber-500/10 p-2 rounded-md border border-amber-500/25 text-[12px] text-amber-400">
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
              className="px-2 py-0.5 rounded-md border border-amber-500/30 bg-white/5 hover:bg-white/10 text-[11.5px] font-medium text-amber-300 min-h-[24px] min-w-[24px] inline-flex items-center justify-center transition-all duration-150 ease-out cursor-pointer focus-visible:ring-2 focus-visible:ring-amber-400 focus-visible:outline-none"
            >
              Open settings
            </button>
          </div>
        </div>
      )}

      {/* Failed Row */}
      {doc.status === 'Failed' && doc.statusNote && (
        <div className="mt-2 bg-red-500/10 p-2 rounded-md border border-red-500/25 text-[12px] text-red-400">
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
                className="px-2 py-0.5 rounded-md border border-red-500/30 bg-white/5 hover:bg-white/10 text-[11.5px] font-medium text-red-300 min-h-[24px] min-w-[24px] inline-flex items-center justify-center transition-all duration-150 ease-out cursor-pointer focus-visible:ring-2 focus-visible:ring-red-400 focus-visible:outline-none"
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
                className="px-2 py-0.5 rounded-md border border-red-500/30 bg-white/5 hover:bg-white/10 text-[11.5px] font-medium text-red-300 min-h-[24px] min-w-[24px] inline-flex items-center justify-center transition-all duration-150 ease-out cursor-pointer focus-visible:ring-2 focus-visible:ring-red-400 focus-visible:outline-none"
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
