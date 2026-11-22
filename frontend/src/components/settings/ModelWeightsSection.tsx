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
    <div className="bg-[#272727] p-4 rounded-lg border border-white/[0.06] space-y-3.5 transition-colors">
      <div className="flex items-center justify-between border-b border-white/[0.04] pb-2.5">
        <div>
          <div className="flex items-center gap-2">
            <HardDrive className="w-4 h-4 text-[#60CDFF]" aria-hidden="true" />
            <span className="text-[13.5px] font-semibold text-[#F3F3F3]">
              Model Weights Management
            </span>
          </div>
          <p className="text-[12px] text-[#A6A6A6] mt-0.5">
            Offline GGUF vision-language model weights for local OCR processing
          </p>
        </div>

        <div>
          {effectiveModelStatus?.downloaded ? (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-sm text-xs font-semibold bg-[#78c697]/15 text-[#78c697] border border-[#78c697]/30">
              <CheckCircle2 className="w-3.5 h-3.5 text-[#78c697]" aria-hidden="true" />
              Downloaded (Verified Local Weights)
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-sm text-xs font-semibold bg-amber-400/15 text-amber-300 border border-amber-500/25">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-400" aria-hidden="true" />
              Not Downloaded (Download required)
            </span>
          )}
        </div>
      </div>

      {/* Model Metadata Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-[1fr_2fr_auto] gap-3 text-xs p-3 rounded-md border border-white/[0.06] bg-white/[0.02]">
        <div>
          <span className="text-[#A6A6A6] block font-medium mb-0.5">Model</span>
          <span className="font-semibold text-[#F3F3F3] font-mono text-[12.5px]">
            PaddleOCR-VL-1.6
          </span>
        </div>
        <div>
          <span className="text-[#A6A6A6] block font-medium mb-0.5">Repo & Revision</span>
          <span
            className="font-medium text-[#F3F3F3] font-mono text-[11.5px] truncate block"
            title={`${effectiveModelStatus?.repo || 'PaddlePaddle/PaddleOCR-VL-1.6-GGUF'} (Revision ${effectiveModelStatus?.revision || 'main'})`}
          >
            {effectiveModelStatus?.repo || 'PaddlePaddle/PaddleOCR-VL-1.6-GGUF'} (Revision {effectiveModelStatus?.revision || 'main'})
          </span>
        </div>
        <div>
          <span className="text-[#A6A6A6] block font-medium mb-0.5">Size</span>
          <span className="font-semibold text-[#F3F3F3] font-mono text-[12.5px]">
            {modelSize}
          </span>
        </div>
      </div>

      {effectiveModelStatus?.error && (
        <div role="alert" className="p-2.5 bg-red-500/10 border border-red-500/30 text-[#e58383] rounded-md text-xs flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0 text-[#e58383]" aria-hidden="true" />
          <span>{effectiveModelStatus.error}</span>
        </div>
      )}

      {effectiveModelStatus?.is_downloading ? (
        <div className="space-y-2 pt-1">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5 font-mono text-[11.5px] text-[#A6A6A6] truncate max-w-[65%]">
              <RefreshCw className="w-3.5 h-3.5 animate-spin text-[#60CDFF] shrink-0" aria-hidden="true" />
              <span className="truncate">{effectiveModelStatus.active_file || 'Downloading weights...'}</span>
            </div>
            <div className="font-mono text-[11.5px] text-[#F3F3F3] font-semibold shrink-0" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {formatBytes(effectiveModelStatus.bytes_downloaded)} / {formatBytes(effectiveModelStatus.total_bytes || TOTAL_MODEL_BYTES)} ({Math.round(effectiveModelStatus.percent)}%)
            </div>
          </div>

          <div className="w-full bg-white/[0.06] h-2 rounded-full overflow-hidden relative">
            <div
              className="bg-[#60CDFF] h-full transition-all duration-200 rounded-full relative overflow-hidden"
              style={{ width: `${effectiveModelStatus.percent}%` }}
            >
              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/40 to-transparent animate-shimmer" />
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
          <div className="text-xs text-[#A6A6A6]">
            {effectiveModelStatus?.downloaded ? (
              <div className="flex items-center gap-1.5 text-[#78c697] font-medium">
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
            className="inline-flex items-center gap-1.5 h-8 px-3.5 bg-[#60CDFF] hover:bg-[#4CC2FF] active:bg-[#0091E6] text-[#000000] rounded-md text-xs font-semibold active:scale-[0.96] transition-all duration-150 cursor-pointer shadow-xs shrink-0"
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
