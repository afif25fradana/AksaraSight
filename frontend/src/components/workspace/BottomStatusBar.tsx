import React from 'react';
import { Cpu } from 'lucide-react';
import { ServerStatusInfo } from '../../types';
import { useVramTelemetry } from '../../hooks/useVramTelemetry';

export interface BottomStatusBarProps {
  serverStatus: ServerStatusInfo | null;
}

export const BottomStatusBar: React.FC<BottomStatusBarProps> = ({
  serverStatus,
}) => {
  const rawStatus = String(serverStatus?.status || 'offline').toLowerCase();
  const currentStatus: 'offline' | 'starting' | 'ready' | 'error' =
    rawStatus === 'ready' || rawStatus === 'starting' || rawStatus === 'error'
      ? rawStatus
      : 'offline';

  const isServerRunning = currentStatus === 'ready';
  const { vram } = useVramTelemetry(currentStatus);

  const statusConfigs = {
    ready: {
      label: 'Engine Ready',
      dotClass: 'bg-[#78c697]',
      textClass: 'text-[#78c697]',
    },
    starting: {
      label: 'Starting Engine...',
      dotClass: 'bg-amber-400',
      textClass: 'text-amber-400',
    },
    error: {
      label: 'Engine Error',
      dotClass: 'bg-red-400',
      textClass: 'text-red-400',
    },
    offline: {
      label: 'Engine Offline',
      dotClass: 'bg-red-400',
      textClass: 'text-[#e58383]',
    },
  };

  const statusConfig = statusConfigs[currentStatus] || statusConfigs.offline;

  const usagePercent =
    vram?.usage_percent ??
    (vram?.total_mb && vram?.used_mb
      ? Math.round((vram.used_mb / vram.total_mb) * 100)
      : 0);

  return (
    <footer
      aria-label="Application Status Bar"
      className="h-[26px] w-full bg-[#202020] border-t border-white/8 flex items-center px-3 select-none shrink-0 z-20 text-[11px] text-[#A6A6A6]"
    >
      {/* Left Stack: Engine Status & VRAM Telemetry */}
      <div className="flex items-center gap-3">
        {/* Engine Status indicator */}
        <div
          className="flex items-center gap-1.5"
          role="status"
          aria-live="polite"
        >
          {currentStatus === 'starting' ? (
            <span className="relative flex h-2 w-2" aria-hidden="true">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
              <span className={`relative inline-flex rounded-full h-2 w-2 ${statusConfig.dotClass}`} />
            </span>
          ) : (
            <span className={`inline-block w-2 h-2 rounded-full ${statusConfig.dotClass}`} aria-hidden="true" />
          )}
          <span className={`font-semibold tracking-tight ${statusConfig.textClass}`}>
            {statusConfig.label}
          </span>
          {serverStatus?.pid != null && (
            <span className="text-[10px] font-mono px-1 rounded bg-white/10 text-[#F3F3F3]">
              PID {serverStatus.pid}
            </span>
          )}
          {isServerRunning && (
            <span className="text-[#929292] font-mono hidden sm:inline">
              · PaddleOCR-VL
            </span>
          )}
        </div>

        {/* Separator */}
        <span className="text-white/20" aria-hidden="true">|</span>

        {/* Live NVML VRAM Telemetry */}
        {vram && vram.available && vram.total_mb ? (
          <div
            className="flex items-center gap-1.5 font-mono text-[11px]"
            title={`GPU: ${vram.device_name || 'NVIDIA'} | VRAM: ${vram.used_mb ?? 0}MB / ${vram.total_mb}MB (${usagePercent}%)`}
            aria-label="VRAM Telemetry Gauge"
          >
            <Cpu className="w-3 h-3 text-[#60CDFF] shrink-0" aria-hidden="true" />
            <span className="text-[#F3F3F3] font-medium hidden md:inline">
              {vram.device_name || 'GPU'}
            </span>
            <span className="text-[#F3F3F3] tabular-nums">
              {vram.used_mb ?? 0} / {vram.total_mb} MB
            </span>
            <div className="w-12 h-1 bg-white/10 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-300 ${
                  usagePercent > 85
                    ? 'bg-red-500'
                    : usagePercent > 65
                      ? 'bg-amber-500'
                      : 'bg-[#60CDFF]'
                }`}
                style={{ width: `${Math.min(100, Math.max(0, usagePercent))}%` }}
              />
            </div>
            <span className="tabular-nums text-[#929292]">
              {usagePercent}%
            </span>
          </div>
        ) : vram && !vram.available ? (
          <div
            className="flex items-center gap-1.5 font-mono text-[11px] text-[#929292] opacity-70"
            title={vram.error || 'VRAM telemetry unavailable (CPU inference)'}
            aria-label="VRAM Telemetry Unavailable"
          >
            <Cpu className="w-3 h-3 text-[#929292] shrink-0" aria-hidden="true" />
            <span>VRAM N/A (CPU)</span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 font-mono text-[11px] text-[#929292] opacity-70">
            <Cpu className="w-3 h-3 text-[#929292] shrink-0" aria-hidden="true" />
            <span>Telemetry</span>
          </div>
        )}
      </div>
    </footer>
  );
};
