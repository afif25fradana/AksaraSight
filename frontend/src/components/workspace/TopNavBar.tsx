import React from 'react';
import { FolderOpen, Play, RefreshCw, Square } from 'lucide-react';
import { ServerStatusInfo } from '../../types';

export interface TopNavBarProps {
  onToggleServer: () => void;
  onOpenOutputFolder: () => void;
  serverStatus: ServerStatusInfo | null;
  isExtracting: boolean;
  isTransitioning?: boolean;
}

export const TopNavBar: React.FC<TopNavBarProps> = ({
  onToggleServer,
  onOpenOutputFolder,
  serverStatus,
  isExtracting,
  isTransitioning = false,
}) => {
  const rawStatus = String(serverStatus?.status || 'offline').toLowerCase();
  const currentStatus: 'offline' | 'starting' | 'ready' | 'error' =
    rawStatus === 'ready' || rawStatus === 'starting' || rawStatus === 'error'
      ? rawStatus
      : 'offline';

  const isServerRunning = currentStatus === 'ready';

  let buttonDisabled = false;
  let buttonTitle = '';
  let buttonAriaLabel = '';
  let buttonText = 'Start Engine';

  if (isServerRunning) {
    if (String(serverStatus?.ownership || '').toLowerCase() === 'external') {
      buttonDisabled = true;
      buttonTitle = `Server managed externally (PID ${serverStatus?.pid || 'external'})`;
      buttonAriaLabel = 'Stop Engine (Disabled - External Server)';
      buttonText = 'Stop Engine';
    } else if (isExtracting) {
      buttonDisabled = true;
      buttonTitle = 'Extraction in progress';
      buttonAriaLabel = 'Stop Engine (Disabled - Extraction in progress)';
      buttonText = 'Stop Engine';
    } else if (isTransitioning) {
      buttonDisabled = true;
      buttonTitle = 'Stopping Engine';
      buttonAriaLabel = 'Stopping Engine';
      buttonText = 'Stopping...';
    } else {
      buttonDisabled = false;
      buttonTitle = 'Stop running llama-server instance';
      buttonAriaLabel = 'Stop Engine';
      buttonText = 'Stop Engine';
    }
  } else {
    if (isTransitioning) {
      buttonDisabled = true;
      buttonTitle = 'Starting Engine';
      buttonAriaLabel = 'Starting Engine';
      buttonText = 'Starting...';
    } else if (isExtracting) {
      buttonDisabled = true;
      buttonTitle = 'Extraction in progress';
      buttonAriaLabel = 'Start Engine';
      buttonText = 'Start Engine';
    } else {
      buttonDisabled = false;
      buttonTitle = 'Start local llama-server backend';
      buttonAriaLabel = 'Start Engine';
      buttonText = 'Start Engine';
    }
  }

  return (
    <header className="h-12 w-full bg-[#202020] border-b border-white/8 flex items-center justify-between px-4 select-none shrink-0 z-20">
      {/* Left: Brand / View Title */}
      <div className="flex items-center gap-3">
        <h1 className="text-[15px] font-semibold text-[#F3F3F3] tracking-tight">
          AksaraSight
        </h1>
        <span className="text-xs text-[#A6A6A6] hidden sm:inline">
          Local Archival & Document OCR
        </span>
      </div>

      {/* Right: Output Folder & Primary Engine Toggle Button */}
      <div className="flex items-center gap-2 sm:gap-2.5">
        {/* Local Output Folder Button */}
        <button
          onClick={onOpenOutputFolder}
          className="h-8 px-3 rounded-sm border border-white/8 hover:border-white/12 bg-white/[0.04] hover:bg-white/[0.08] text-[#F3F3F3] active:scale-[0.98] transition-all duration-100 ease-out flex items-center gap-1.5 text-[13px] font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-[#60CDFF] cursor-pointer"
          type="button"
          aria-label="Output Folder"
          title="Local output folder"
        >
          <FolderOpen className="w-4 h-4 text-[#60CDFF]" aria-hidden="true" />
          <span className="hidden md:inline">Output Folder</span>
        </button>

        {/* Start / Stop Engine Toggle Button */}
        {isServerRunning ? (
          <button
            type="button"
            onClick={buttonDisabled ? undefined : onToggleServer}
            disabled={buttonDisabled}
            className={`h-8 px-3 sm:w-[116px] rounded-sm border border-[var(--danger)]/30 text-[var(--danger)] flex items-center justify-center gap-1.5 text-[13px] font-semibold active:scale-[0.98] transition-all duration-100 ease-out focus-visible:ring-2 focus-visible:ring-[var(--danger)] focus-visible:outline-none shrink-0 ${
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
            className={`h-8 px-3 sm:w-[116px] rounded-sm bg-[#60CDFF] text-[#000000] flex items-center justify-center gap-1.5 text-[13px] font-semibold active:scale-[0.98] transition-all duration-100 ease-out focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none shrink-0 ${
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
      </div>
    </header>
  );
};
