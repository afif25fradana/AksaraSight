import React from 'react';
import { Download, RefreshCw, CheckCircle2, AlertTriangle } from 'lucide-react';
import { BackendSettings, DoctorReport, RuntimeStatusInfo } from '../../types';

export interface ManagedRuntimeSectionProps {
  formData: BackendSettings;
  setFormData: React.Dispatch<React.SetStateAction<BackendSettings>>;
  effectiveRuntimeStatus: RuntimeStatusInfo | null;
  doctorReport: DoctorReport | null;
  isRefreshingHardware: boolean;
  isStartingRuntimeDownload: boolean;
  onRefreshHardware: () => void;
  onDownloadRuntime: () => void;
  formatBytes: (bytes: number) => string;
}

export const ManagedRuntimeSection: React.FC<ManagedRuntimeSectionProps> = ({
  formData,
  setFormData,
  effectiveRuntimeStatus,
  doctorReport,
  isRefreshingHardware,
  isStartingRuntimeDownload,
  onRefreshHardware,
  onDownloadRuntime,
  formatBytes,
}) => {
  const [targetIndicator, setTargetIndicator] = React.useState<{ left: number; width: number }>({ left: 2, width: 0 });
  const targetContainerRef = React.useRef<HTMLDivElement>(null);
  const targetRefs = React.useRef<{ [key: string]: HTMLButtonElement | null }>({});

  React.useEffect(() => {
    const currentTarget = formData.managed_backend_override || 'auto';
    if (targetContainerRef.current && targetRefs.current[currentTarget]) {
      const cRect = targetContainerRef.current.getBoundingClientRect();
      const tRect = targetRefs.current[currentTarget]!.getBoundingClientRect();
      setTargetIndicator({ left: tRect.left - cRect.left, width: tRect.width });
    }
  }, [formData.managed_backend_override]);

  const hardwareCheck = React.useMemo(() => {
    if (!doctorReport?.checks) return null;
    return doctorReport.checks.find(
      (c) =>
        c.category?.toLowerCase().includes('hardware') ||
        c.title?.toLowerCase().includes('hardware') ||
        c.title?.toLowerCase().includes('device')
    );
  }, [doctorReport]);

  const hardwareDetail = React.useMemo(() => {
    if (!hardwareCheck) return null;
    if (typeof hardwareCheck.details === 'string') return hardwareCheck.details;
    if (Array.isArray(hardwareCheck.details)) return hardwareCheck.details.join(', ');
    return hardwareCheck.title;
  }, [hardwareCheck]);

  return (
    <div className="bg-white dark:bg-[var(--bg-elevated)] rounded-lg p-3.5 border border-[#E5E2D9] dark:border-[var(--border)] space-y-3 transition-colors animate-fade-in">
      {/* Recommended Hardware Acceleration Banner */}
      <div className="flex items-center justify-between p-2.5 bg-[#0F766E]/5 dark:bg-[var(--accent)]/10 rounded-lg border border-[#0F766E]/15 dark:border-[var(--accent)]/20">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-[#0F766E] dark:bg-[var(--accent)]" />
          <span className="text-xs font-semibold text-[#0F766E] dark:text-[var(--accent)]">
            Detected Hardware:
          </span>
          <span className="text-xs font-mono font-medium text-[#14213D] dark:text-[var(--text-1)]">
            {hardwareDetail || 'Detecting hardware...'}
          </span>
        </div>
        <button
          type="button"
          onClick={onRefreshHardware}
          disabled={isRefreshingHardware}
          className="text-xs font-medium text-[#0F766E] dark:text-[var(--accent)] hover:underline flex items-center gap-1 cursor-pointer disabled:opacity-50"
        >
          <RefreshCw className={`w-3 h-3 ${isRefreshingHardware ? 'animate-spin' : ''}`} />
          <span>Re-detect</span>
        </button>
      </div>

      {/* Target Acceleration Backend Switcher */}
      <div className="flex items-center justify-between pt-1">
        <div>
          <span className="text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)] block">
            Hardware Acceleration Target
          </span>
          <p className="text-[11.5px] text-[#5A6478] dark:text-[var(--text-2)] mt-0.5">
            Select instruction set / compute runtime for local binary
          </p>
        </div>
        <div 
          ref={targetContainerRef}
          className="relative inline-flex p-0.5 bg-[#F5F4F0] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md gap-0.5"
        >
          <div 
            className="absolute top-0.5 bottom-0.5 bg-white dark:bg-[var(--bg-elevated)] rounded shadow-2xs transition-all duration-200 ease-out"
            style={{ left: `${targetIndicator.left}px`, width: `${targetIndicator.width}px` }}
          />
          {(['auto', 'cuda', 'vulkan', 'cpu'] as const).map((backendOption) => (
            <button
              key={backendOption}
              ref={(el) => { targetRefs.current[backendOption] = el; }}
              type="button"
              onClick={() => setFormData((prev) => ({ ...prev, managed_backend_override: backendOption }))}
              className={`relative z-10 px-2.5 py-0.5 rounded text-[12px] font-medium whitespace-nowrap cursor-pointer active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] focus-visible:outline-none ${
                (formData.managed_backend_override || 'auto') === backendOption 
                  ? 'text-[#14213D] dark:text-[var(--text-1)]' 
                  : 'text-[#374151] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)]'
              }`}
            >
              {backendOption}
            </button>
          ))}
        </div>
      </div>

      <div className="pt-0.5">
        <div className="flex items-center justify-between text-[12px] mb-1">
          <span className="font-medium text-[#14213D] dark:text-[var(--text-1)]">
            Executable Location:
          </span>
          {effectiveRuntimeStatus?.installed ? (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-[#15803D]/10 text-[#14532D] dark:bg-[var(--success)]/10 dark:text-[var(--success)] border border-[#15803D]/25 dark:border-[var(--success)]/30">
              <CheckCircle2 className="w-3 h-3 text-[#15803D] dark:text-[var(--success)]" aria-hidden="true" />
              Installed (Verified Local Binary)
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-amber-500/10 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400 border border-amber-500/25 dark:border-amber-500/30">
              <AlertTriangle className="w-3 h-3 text-amber-600 dark:text-amber-400" aria-hidden="true" />
              Not Installed
            </span>
          )}
        </div>
        <div className="font-mono text-[11.5px] text-[#374151] dark:text-[var(--text-2)] truncate bg-[#F9F8F5] dark:bg-[var(--bg-base)] px-2.5 py-1.5 rounded border border-[#E5E2D9] dark:border-[var(--border)]" title={effectiveRuntimeStatus?.executable_path || effectiveRuntimeStatus?.expected_path || ''}>
          {effectiveRuntimeStatus?.executable_path || effectiveRuntimeStatus?.expected_path || `%LOCALAPPDATA%\\AksaraSight\\runtimes\\llama-cpp\\b11361-${formData.managed_backend_override || 'auto'}\\llama-server.exe`}
        </div>
      </div>

      {effectiveRuntimeStatus?.error && (
        <div role="alert" className="p-2.5 bg-red-50 dark:bg-[var(--danger)]/10 border border-red-200 dark:border-[var(--danger)]/30 text-red-700 dark:text-[var(--danger)] rounded-lg text-xs flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0 text-red-600 dark:text-[var(--danger)]" aria-hidden="true" />
          <span>{effectiveRuntimeStatus.error}</span>
        </div>
      )}

      {effectiveRuntimeStatus?.is_downloading ? (
        <div className="space-y-2 pt-1">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5 font-mono text-[11.5px] text-[#374151] dark:text-[var(--text-2)] truncate max-w-[70%]">
              <RefreshCw className="w-3.5 h-3.5 animate-spin text-[#0F766E] dark:text-[var(--accent)] shrink-0" aria-hidden="true" />
              <span className="truncate">{effectiveRuntimeStatus.message || 'Downloading runtime...'}</span>
              {effectiveRuntimeStatus?.total_parts && effectiveRuntimeStatus.total_parts > 1 ? (
                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10.5px] font-sans font-medium bg-[#E5E2D9] dark:bg-[var(--border)] text-[#14213D] dark:text-[var(--text-1)] shrink-0">
                  Part {effectiveRuntimeStatus.part || 1} of {effectiveRuntimeStatus.total_parts}
                </span>
              ) : null}
            </div>
            <div className="font-mono text-[11.5px] text-[#14213D] dark:text-[var(--text-1)] font-semibold shrink-0" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {effectiveRuntimeStatus.total_bytes > 0
                ? `${formatBytes(effectiveRuntimeStatus.bytes_downloaded)} / ${formatBytes(effectiveRuntimeStatus.total_bytes)} (${Math.round(effectiveRuntimeStatus.percent)}%)`
                : `${Math.round(effectiveRuntimeStatus.percent)}%`}
            </div>
          </div>

          <div className="w-full bg-[#E5E2D9] dark:bg-[var(--bg-base)] h-2 rounded-full overflow-hidden relative">
            <div
              className="bg-[#0F766E] dark:bg-[var(--accent)] h-full transition-all duration-200 rounded-full relative overflow-hidden"
              style={{ width: `${Math.min(100, Math.max(0, effectiveRuntimeStatus.percent))}%` }}
            >
              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/40 dark:via-white/30 to-transparent animate-shimmer" />
            </div>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-between pt-1">
          <div className="text-xs text-[#5A6478] dark:text-[var(--text-2)]">
            {effectiveRuntimeStatus?.installed
              ? 'Managed llama.cpp runtime binary is verified and ready.'
              : 'Download the pinned llama.cpp build for local inference.'}
          </div>
          <button
            type="button"
            onClick={onDownloadRuntime}
            disabled={isStartingRuntimeDownload}
            className="h-8 px-3.5 bg-[#0F766E] dark:bg-[var(--accent)] hover:bg-[#115E59] dark:hover:bg-[var(--accent)]/90 active:bg-[#0d4f4b] text-white dark:text-[var(--bg-base)] rounded-lg text-xs font-semibold active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out flex items-center gap-1.5 cursor-pointer shadow-xs shrink-0 disabled:opacity-50"
          >
            <Download className="w-3.5 h-3.5" aria-hidden="true" />
            <span>
              {effectiveRuntimeStatus?.installed ? 'Re-download / Verify Runtime' : 'Download Runtime'}
            </span>
          </button>
        </div>
      )}
    </div>
  );
};
