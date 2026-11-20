import React from 'react';
import { HardDrive, CheckCircle2, AlertTriangle, RefreshCw, Download } from 'lucide-react';
import { ModelStatusInfo } from '../../types';

export interface ModelWeightsSectionProps {
  effectiveModelStatus: ModelStatusInfo | null;
  onDownloadModel: () => void;
  onCancelModelDownload: () => void;
  formatBytes: (bytes: number) => string;
}

export const TOTAL_MODEL_BYTES = 1817539616;

export const ModelWeightsSection: React.FC<ModelWeightsSectionProps> = ({
  effectiveModelStatus,
  onDownloadModel,
  onCancelModelDownload,
  formatBytes,
}) => {
  const modelSize = formatBytes(effectiveModelStatus?.total_bytes || TOTAL_MODEL_BYTES);

  return (
    <div className="bg-white dark:bg-[var(--bg-elevated)] p-4 rounded-lg border border-[#8A94A6]/25 dark:border-[var(--border)] space-y-3.5 transition-colors">
      <div className="flex items-center justify-between border-b border-[#E5E2D9]/70 dark:border-[var(--border)] pb-2.5">
        <div>
          <div className="flex items-center gap-2">
            <HardDrive className="w-4 h-4 text-[#0F766E] dark:text-[var(--accent)]" aria-hidden="true" />
            <span className="text-[13.5px] font-semibold text-[#14213D] dark:text-[var(--text-1)]">
              Model Weights Management
            </span>
          </div>
          <p className="text-[12px] text-[#5A6478] dark:text-[var(--text-2)] mt-0.5">
            Offline GGUF vision-language model weights for local OCR processing
          </p>
        </div>

        <div>
          {effectiveModelStatus?.downloaded ? (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-[#15803D]/10 text-[#14532D] dark:bg-[var(--success)]/10 dark:text-[var(--success)] border border-[#15803D]/25 dark:border-[var(--success)]/30">
              <CheckCircle2 className="w-3.5 h-3.5 text-[#15803D] dark:text-[var(--success)]" aria-hidden="true" />
              Downloaded (Verified Local Weights)
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-amber-500/10 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400 border border-amber-500/25 dark:border-amber-500/30">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" aria-hidden="true" />
              Not Downloaded (Download required)
            </span>
          )}
        </div>
      </div>

      {/* Model Metadata Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-[1fr_2fr_auto] gap-3 text-xs bg-[#FAF9F5] dark:bg-[var(--bg-base)] p-3 rounded-lg border border-[#E5E2D9] dark:border-[var(--border)]">
        <div>
          <span className="text-[#5A6478] dark:text-[var(--text-2)] block font-medium mb-0.5">Model</span>
          <span className="font-semibold text-[#14213D] dark:text-[var(--text-1)] font-mono text-[12.5px]">
            PaddleOCR-VL-1.6
          </span>
        </div>
        <div>
          <span className="text-[#5A6478] dark:text-[var(--text-2)] block font-medium mb-0.5">Repo & Revision</span>
          <span
            className="font-medium text-[#14213D] dark:text-[var(--text-1)] font-mono text-[11.5px] truncate block"
            title={`${effectiveModelStatus?.repo || 'PaddlePaddle/PaddleOCR-VL-1.6-GGUF'} (Revision ${effectiveModelStatus?.revision || 'main'})`}
          >
            {effectiveModelStatus?.repo || 'PaddlePaddle/PaddleOCR-VL-1.6-GGUF'} (Revision {effectiveModelStatus?.revision || 'main'})
          </span>
        </div>
        <div>
          <span className="text-[#5A6478] dark:text-[var(--text-2)] block font-medium mb-0.5">Size</span>
          <span className="font-semibold text-[#14213D] dark:text-[var(--text-1)] font-mono text-[12.5px]">
            {modelSize}
          </span>
        </div>
      </div>

      {effectiveModelStatus?.error && (
        <div role="alert" className="p-2.5 bg-red-50 dark:bg-[var(--danger)]/10 border border-red-200 dark:border-[var(--danger)]/30 text-red-700 dark:text-[var(--danger)] rounded-lg text-xs flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0 text-red-600 dark:text-[var(--danger)]" aria-hidden="true" />
          <span>{effectiveModelStatus.error}</span>
        </div>
      )}

      {effectiveModelStatus?.is_downloading ? (
        <div className="space-y-2 pt-1">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5 font-mono text-[11.5px] text-[#374151] dark:text-[var(--text-2)] truncate max-w-[65%]">
              <RefreshCw className="w-3.5 h-3.5 animate-spin text-[#0F766E] dark:text-[var(--accent)] shrink-0" aria-hidden="true" />
              <span className="truncate">{effectiveModelStatus.active_file || 'Downloading weights...'}</span>
            </div>
            <div className="font-mono text-[11.5px] text-[#14213D] dark:text-[var(--text-1)] font-semibold shrink-0" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {formatBytes(effectiveModelStatus.bytes_downloaded)} / {formatBytes(effectiveModelStatus.total_bytes || TOTAL_MODEL_BYTES)} ({Math.round(effectiveModelStatus.percent)}%)
            </div>
          </div>

          <div className="w-full bg-[#E5E2D9] dark:bg-[var(--bg-base)] h-2 rounded-full overflow-hidden relative">
            <div
              className="bg-[#0F766E] dark:bg-[var(--accent)] h-full transition-all duration-200 rounded-full relative overflow-hidden"
              style={{ width: `${effectiveModelStatus.percent}%` }}
            >
              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/40 dark:via-white/30 to-transparent animate-shimmer" />
            </div>
          </div>

          <div className="flex justify-end pt-1">
            <button
              type="button"
              onClick={onCancelModelDownload}
              className="h-7 px-3 bg-red-600 hover:bg-red-700 active:bg-red-800 text-white rounded-md text-xs font-semibold active:scale-[0.96] transition-all duration-150 cursor-pointer shadow-2xs"
            >
              Cancel Download
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-between pt-1">
          <div className="text-xs text-[#5A6478] dark:text-[var(--text-2)]">
            {effectiveModelStatus?.downloaded ? (
              <div className="flex items-center gap-1.5 text-[#15803D] dark:text-[var(--success)] font-medium">
                <CheckCircle2 className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                <span>Model verified & ready for offline inference.</span>
              </div>
            ) : (
              <span>Download pinned weights to run OCR without online Hugging Face hub requests.</span>
            )}
          </div>
          <button
            type="button"
            onClick={onDownloadModel}
            className="h-8 px-3.5 bg-[#0F766E] dark:bg-[var(--accent)] hover:bg-[#115E59] dark:hover:bg-[var(--accent)]/90 active:bg-[#0d4f4b] text-white dark:text-[var(--bg-base)] rounded-lg text-xs font-semibold active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out flex items-center gap-1.5 cursor-pointer shadow-xs shrink-0"
          >
            <Download className="w-3.5 h-3.5" aria-hidden="true" />
            <span>
              {effectiveModelStatus?.downloaded ? 'Re-download Weights' : 'Download Pinned Model'}
            </span>
          </button>
        </div>
      )}
    </div>
  );
};
