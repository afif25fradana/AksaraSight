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
    <div className="pt-3 border-t border-white/[0.04] space-y-3 transition-colors animate-fade-in">
      {/* Recommended Hardware Acceleration Banner */}
      <div className="flex items-center justify-between p-2.5 bg-[#60CDFF]/10 rounded-md border border-[#60CDFF]/20">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#60CDFF] opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-[#60CDFF]" />
          </span>
          <span className="text-xs font-semibold text-[#60CDFF]">
            Detected Hardware:
          </span>
          <span className="text-xs font-mono font-medium text-[#F3F3F3]">
            {hardwareDetail || 'Detecting hardware...'}
          </span>
        </div>
        <button
          type="button"
          onClick={onRefreshHardware}
          disabled={isRefreshingHardware}
          className="text-xs font-medium text-[#60CDFF] hover:text-[#4CC2FF] hover:underline flex items-center gap-1 cursor-pointer disabled:opacity-50"
        >
          <RefreshCw className={`w-3 h-3 ${isRefreshingHardware ? 'animate-spin' : ''}`} />
          <span>Re-detect</span>
        </button>
      </div>

      {/* Target Acceleration Backend Switcher */}
      <div className="flex items-center justify-between pt-1">
        <div>
          <span className="text-[13px] font-medium text-[#F3F3F3] block">
            Hardware Acceleration Target
          </span>
          <p className="text-[11.5px] text-[#A6A6A6] mt-0.5">
            Select instruction set / compute runtime for local binary
          </p>
        </div>
        <div 
          ref={targetContainerRef}
          className="relative inline-flex p-0.5 bg-black/20 border border-white/[0.06] rounded-md gap-0.5"
        >
          <div 
            className="absolute top-0.5 bottom-0.5 bg-[#383838] rounded shadow-xs transition-all duration-200 ease-out"
            style={{ left: `${targetIndicator.left}px`, width: `${targetIndicator.width}px` }}
          />
          {(['auto', 'cuda', 'vulkan', 'cpu'] as const).map((backendOption) => (
            <button
              key={backendOption}
              ref={(el) => { targetRefs.current[backendOption] = el; }}
              type="button"
              onClick={() => setFormData((prev) => ({ ...prev, managed_backend_override: backendOption }))}
              className={`relative z-10 px-2.5 py-0.5 rounded text-[12px] font-medium whitespace-nowrap cursor-pointer active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none ${
                (formData.managed_backend_override || 'auto') === backendOption 
                  ? 'text-[#F3F3F3]' 
                  : 'text-[#A6A6A6] hover:text-[#F3F3F3]'
              }`}
            >
              {backendOption}
            </button>
          ))}
        </div>
      </div>

      <div className="pt-0.5">
        <div className="flex items-center justify-between text-[12px] mb-1">
          <span className="font-medium text-[#F3F3F3]">
            Executable Location:
          </span>
          {effectiveRuntimeStatus?.installed ? (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-sm text-[11px] font-semibold bg-[#78c697]/15 text-[#78c697] border border-[#78c697]/30">
              <CheckCircle2 className="w-3 h-3 text-[#78c697]" aria-hidden="true" />
              Installed (Verified Local Binary)
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-sm text-[11px] font-semibold bg-amber-400/15 text-amber-300 border border-amber-500/25">
              <AlertTriangle className="w-3 h-3 text-amber-400" aria-hidden="true" />
              Not Installed
            </span>
          )}
        </div>
        <div className="font-mono text-[11.5px] text-[#A6A6A6] truncate bg-white/[0.03] px-2.5 py-1.5 rounded-md border border-white/[0.06]" title={effectiveRuntimeStatus?.executable_path || effectiveRuntimeStatus?.expected_path || ''}>
          {effectiveRuntimeStatus?.executable_path || effectiveRuntimeStatus?.expected_path || `%LOCALAPPDATA%\\AksaraSight\\runtimes\\llama-cpp\\b11361-${formData.managed_backend_override || 'auto'}\\llama-server.exe`}
        </div>
      </div>

      {effectiveRuntimeStatus?.error && (
        <div role="alert" className="p-2.5 bg-red-500/10 border border-red-500/30 text-[#e58383] rounded-md text-xs flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0 text-[#e58383]" aria-hidden="true" />
          <span>{effectiveRuntimeStatus.error}</span>
        </div>
      )}

      {effectiveRuntimeStatus?.is_downloading ? (
        <div className="space-y-2 pt-1">
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5 font-mono text-[11.5px] text-[#A6A6A6] truncate max-w-[70%]">
              <RefreshCw className="w-3.5 h-3.5 animate-spin text-[#60CDFF] shrink-0" aria-hidden="true" />
              <span className="truncate">{effectiveRuntimeStatus.message || 'Downloading runtime...'}</span>
              {effectiveRuntimeStatus?.total_parts && effectiveRuntimeStatus.total_parts > 1 ? (
                <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm text-[10.5px] font-sans font-medium bg-white/10 text-[#F3F3F3] shrink-0">
                  Part {effectiveRuntimeStatus.part || 1} of {effectiveRuntimeStatus.total_parts}
                </span>
              ) : null}
            </div>
            <div className="font-mono text-[11.5px] text-[#F3F3F3] font-semibold shrink-0" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {effectiveRuntimeStatus.total_bytes > 0
                ? `${formatBytes(effectiveRuntimeStatus.bytes_downloaded)} / ${formatBytes(effectiveRuntimeStatus.total_bytes)} (${Math.round(effectiveRuntimeStatus.percent)}%)`
                : `${Math.round(effectiveRuntimeStatus.percent)}%`}
            </div>
          </div>

          <div className="w-full bg-white/[0.06] h-2 rounded-full overflow-hidden relative">
            <div
              className="bg-[#60CDFF] h-full transition-all duration-200 rounded-full relative overflow-hidden"
              style={{ width: `${Math.min(100, Math.max(0, effectiveRuntimeStatus.percent))}%` }}
            >
              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/40 to-transparent animate-shimmer" />
            </div>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-between pt-1">
          <div className="text-xs text-[#A6A6A6]">
            {effectiveRuntimeStatus?.installed
              ? 'Managed llama.cpp runtime binary is verified and ready.'
              : 'Download the pinned llama.cpp build for local inference.'}
          </div>
          <button
            type="button"
            onClick={onDownloadRuntime}
            disabled={isStartingRuntimeDownload}
            className="inline-flex items-center gap-1.5 h-8 px-3.5 bg-[#60CDFF] hover:bg-[#4CC2FF] active:bg-[#0091E6] text-[#000000] rounded-md text-xs font-semibold active:scale-[0.96] transition-all duration-150 cursor-pointer shadow-xs shrink-0 disabled:opacity-50"
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
