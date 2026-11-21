import React from 'react';
import { Cpu, FolderOpen, Play, RefreshCw, Square, Terminal } from 'lucide-react';
import { EngineSettings, ServerStatusInfo, VramTelemetry } from '../../types';

export interface TopNavBarProps {
  currentTab: 'workspace' | 'settings' | 'queue';
  onSelectTab: (tab: any) => void;
  engineSettings: EngineSettings;
  onToggleServer: () => void;
  onOpenServerLogs: () => void;
  onOpenOutputFolder: () => void;
  theme?: 'light' | 'dark';
  onToggleTheme?: (e?: React.SyntheticEvent) => void;
  serverStatus: ServerStatusInfo | null;
  isExtracting: boolean;
  isTransitioning?: boolean;
  vram?: VramTelemetry | null;
}

export const TopNavBar: React.FC<TopNavBarProps> = ({
  currentTab,
  onSelectTab,
  engineSettings: _engineSettings,
  onToggleServer,
  onOpenServerLogs,
  onOpenOutputFolder,
  serverStatus,
  isExtracting,
  isTransitioning = false,
  vram,
}) => {
  const rawStatus = String(serverStatus?.status || 'offline').toLowerCase();
  const currentStatus: 'offline' | 'starting' | 'ready' | 'error' =
    rawStatus === 'ready' || rawStatus === 'starting' || rawStatus === 'error'
      ? rawStatus
      : 'offline';

  const isServerRunning = currentStatus === 'ready';

  const statusConfigs = {
    ready: {
      label: 'Local Engine Ready',
      wrapperClass: 'bg-[#15803D]/10 border-[#15803D]/25 text-[#78c697]',
      dotClass: 'bg-[#78c697]',
    },
    starting: {
      label: 'Engine Starting...',
      wrapperClass: 'bg-amber-500/10 border-amber-500/25 text-amber-400',
      dotClass: 'bg-amber-400',
    },
    error: {
      label: 'Engine Error',
      wrapperClass: 'bg-red-500/10 border-red-500/25 text-red-400',
      dotClass: 'bg-red-400',
    },
    offline: {
      label: 'Engine Offline',
      wrapperClass: 'bg-red-500/10 border-red-500/25 text-[#e58383]',
      dotClass: 'bg-red-400',
    },
  };

  const statusConfig = statusConfigs[currentStatus] || statusConfigs.offline;

  let buttonDisabled = false;
  let buttonTitle = '';
  let buttonAriaLabel = '';
  let buttonText = 'Start Server';

  if (isServerRunning) {
    if (String(serverStatus?.ownership || '').toLowerCase() === 'external') {
      buttonDisabled = true;
      buttonTitle = `Server managed externally (PID ${serverStatus?.pid || 'external'})`;
      buttonAriaLabel = 'Stop Server (Disabled - External Server)';
      buttonText = 'Stop Server';
    } else if (isExtracting) {
      buttonDisabled = true;
      buttonTitle = 'Extraction in progress';
      buttonAriaLabel = 'Stop Server (Disabled - Extraction in progress)';
      buttonText = 'Stop Server';
    } else if (isTransitioning) {
      buttonDisabled = true;
      buttonTitle = 'Stopping Server';
      buttonAriaLabel = 'Stopping Server';
      buttonText = 'Stopping...';
    } else {
      buttonDisabled = false;
      buttonTitle = 'Stop running llama-server instance';
      buttonAriaLabel = 'Stop Server';
      buttonText = 'Stop Server';
    }
  } else {
    if (isTransitioning) {
      buttonDisabled = true;
      buttonTitle = 'Starting Server';
      buttonAriaLabel = 'Starting Server';
      buttonText = 'Starting...';
    } else if (isExtracting) {
      buttonDisabled = true;
      buttonTitle = 'Extraction in progress';
      buttonAriaLabel = 'Start Server';
      buttonText = 'Start Server';
    } else {
      buttonDisabled = false;
      buttonTitle = 'Start local llama-server backend';
      buttonAriaLabel = 'Start Server';
      buttonText = 'Start Server';
    }
  }

  return (
    <header className="h-12 w-full bg-[#202020] border-b border-white/8 flex items-center justify-between px-4 select-none shrink-0 z-20">
      {/* Left: Brand / View Title & Navigation */}
      <div className="flex items-center gap-5">
        <div className="flex items-center gap-3">
          <h1 className="text-[15px] font-semibold text-[#F3F3F3] tracking-tight">
            AksaraSight
          </h1>
          <span className="text-xs text-[#A6A6A6] hidden sm:inline">
            Local Archival & Document OCR
          </span>
        </div>

        <nav className="flex items-center gap-2" aria-label="Main Navigation">
          <button
            type="button"
            onClick={() => onSelectTab('workspace')}
            className={`text-[13px] font-medium px-2.5 py-1 rounded-sm transition-colors cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none ${
              currentTab === 'workspace'
                ? 'text-[#F3F3F3] bg-white/[0.08]'
                : 'text-[#A6A6A6] hover:text-[#F3F3F3] hover:bg-white/[0.04]'
            }`}
          >
            Workspace
          </button>
          <button
            type="button"
            onClick={() => onSelectTab('settings')}
            className={`text-[13px] font-medium px-2.5 py-1 rounded-sm transition-colors cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none ${
              currentTab === 'settings'
                ? 'text-[#F3F3F3] bg-white/[0.08]'
                : 'text-[#A6A6A6] hover:text-[#F3F3F3] hover:bg-white/[0.04]'
            }`}
          >
            Settings
          </button>
        </nav>
      </div>

      {/* Right: Engine Status Indicator, VRAM Gauge, Server Controls, Server Logs, Output Folder */}
      <div className="flex items-center gap-2 sm:gap-2.5">
        {/* VRAM Telemetry Gauge Badge */}
        {vram && vram.available && vram.total_mb ? (
          <div
            className="hidden xl:flex items-center gap-1.5 px-2.5 h-8 rounded-sm border border-white/8 bg-white/[0.03] text-[11px] font-mono select-none"
            title={`GPU: ${vram.device_name || 'NVIDIA'} | VRAM: ${vram.used_mb ?? 0}MB / ${vram.total_mb}MB`}
            aria-label="VRAM Telemetry Gauge"
          >
            <Cpu className="w-3.5 h-3.5 text-[#60CDFF] shrink-0" aria-hidden="true" />
            <span className="font-semibold text-[#F3F3F3]">VRAM</span>
            <span className="text-[#A6A6A6] tabular-nums">
              {((vram.used_mb || 0) / 1024).toFixed(1)} / {((vram.total_mb || 0) / 1024).toFixed(1)} GB
            </span>
            <div className="w-10 h-1.5 bg-white/10 rounded-full overflow-hidden ml-0.5">
              <div
                className={`h-full rounded-full transition-all duration-300 ${
                  (vram.usage_percent || 0) > 85
                    ? 'bg-red-500'
                    : (vram.usage_percent || 0) > 65
                      ? 'bg-amber-500'
                      : 'bg-[#60CDFF]'
                }`}
                style={{
                  width: `${Math.min(
                    100,
                    Math.max(
                      0,
                      vram.usage_percent ?? Math.round(((vram.used_mb || 0) / vram.total_mb) * 100)
                    )
                  )}%`,
                }}
              />
            </div>
          </div>
        ) : vram && !vram.available ? (
          <div
            className="hidden xl:flex items-center gap-1.5 px-2.5 h-8 rounded-sm border border-white/8 bg-white/[0.02] text-[11px] font-mono text-[#929292] select-none opacity-60"
            title={vram.error || 'VRAM telemetry unavailable (CPU inference)'}
            aria-label="VRAM Telemetry Unavailable"
          >
            <Cpu className="w-3.5 h-3.5 text-[#929292] shrink-0" aria-hidden="true" />
            <span className="font-medium">VRAM N/A</span>
          </div>
        ) : null}

        {/* Engine status indicator */}
        <div
          className={`flex items-center gap-2 px-2.5 h-8 rounded-sm border select-none transition-colors ${statusConfig.wrapperClass}`}
          role="status"
          aria-live="polite"
        >
          {currentStatus === 'starting' ? (
            <span className="relative flex h-2 w-2" aria-hidden="true">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
              <span className={`relative inline-flex rounded-full h-2 w-2 ${statusConfig.dotClass}`}></span>
            </span>
          ) : (
            <span className={`inline-block w-2 h-2 rounded-full ${statusConfig.dotClass}`} aria-hidden="true" />
          )}
          <span className="font-semibold text-[12px] whitespace-nowrap tracking-tight">
            {statusConfig.label}
          </span>
          {serverStatus?.pid != null && (
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/10 font-medium">
              PID {serverStatus.pid}
            </span>
          )}
          {isServerRunning && (
            <span className="text-[11px] text-[#A6A6A6] font-medium hidden md:inline">
              · PaddleOCR-VL
            </span>
          )}
        </div>

        {/* Start / Stop Server Toggle Button */}
        {isServerRunning ? (
          <button
            type="button"
            onClick={buttonDisabled ? undefined : onToggleServer}
            disabled={buttonDisabled}
            className={`h-8 w-8 sm:w-[108px] rounded-sm border border-[var(--danger)]/30 text-[var(--danger)] flex items-center justify-center gap-1.5 text-[12px] font-semibold active:scale-[0.98] transition-all duration-100 ease-out focus-visible:ring-2 focus-visible:ring-[var(--danger)] focus-visible:outline-none shrink-0 ${
              buttonDisabled
                ? 'cursor-not-allowed opacity-50'
                : 'hover:border-[var(--danger)]/60 bg-[var(--danger)]/10 hover:bg-[var(--danger)]/20 cursor-pointer'
            }`}
            aria-label={buttonAriaLabel}
            title={buttonTitle}
          >
            {isTransitioning ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin shrink-0" aria-hidden="true" />
            ) : (
              <Square className="w-3.5 h-3.5 fill-current shrink-0" aria-hidden="true" />
            )}
            <span className="hidden sm:inline whitespace-nowrap">{buttonText}</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={buttonDisabled ? undefined : onToggleServer}
            disabled={buttonDisabled}
            className={`h-8 w-8 sm:w-[108px] rounded-sm bg-[#60CDFF] text-[#000000] flex items-center justify-center gap-1.5 text-[12px] font-semibold active:scale-[0.98] transition-all duration-100 ease-out focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none shrink-0 ${
              buttonDisabled
                ? 'cursor-not-allowed opacity-50'
                : 'hover:bg-[#4CC2FF] active:bg-[#0091E6] cursor-pointer'
            }`}
            aria-label={buttonAriaLabel}
            title={buttonTitle}
          >
            {isTransitioning ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin shrink-0" aria-hidden="true" />
            ) : (
              <Play className="w-3.5 h-3.5 fill-current shrink-0" aria-hidden="true" />
            )}
            <span className="hidden sm:inline whitespace-nowrap">{buttonText}</span>
          </button>
        )}

        {/* Server Logs Button */}
        <button
          type="button"
          onClick={onOpenServerLogs}
          className="h-8 px-2.5 rounded-sm border border-white/8 hover:border-white/12 bg-white/[0.04] hover:bg-white/[0.08] text-[#F3F3F3] flex items-center gap-1.5 text-[12px] font-medium active:scale-[0.98] transition-all duration-100 ease-out cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
          title="View server logs"
          aria-label="Server Logs"
        >
          <Terminal className="w-4 h-4 text-[#A6A6A6]" aria-hidden="true" />
          <span className="hidden lg:inline">Server Logs</span>
        </button>

        {/* Local Output Folder Button */}
        <button
          onClick={onOpenOutputFolder}
          className="h-8 px-3 rounded-sm border border-white/8 hover:border-white/12 bg-white/[0.04] hover:bg-white/[0.08] text-[#F3F3F3] active:scale-[0.98] transition-all duration-100 ease-out flex items-center gap-1.5 text-[12px] font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-[#60CDFF] cursor-pointer"
          type="button"
          aria-label="Output Folder"
          title="Local output folder"
        >
          <FolderOpen className="w-4 h-4 text-[#60CDFF]" aria-hidden="true" />
          <span className="hidden md:inline">Output Folder</span>
        </button>
      </div>
    </header>
  );
};
