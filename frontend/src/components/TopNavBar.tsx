import React from 'react';
import { FolderOpen, Play, Square, Terminal } from 'lucide-react';
import { EngineSettings, ServerStatusInfo } from '../types';

interface TopNavBarProps {
  currentTab: 'workspace' | 'settings';
  onSelectTab: (tab: 'workspace' | 'settings') => void;
  engineSettings: EngineSettings;
  onToggleServer: () => void;
  onOpenServerLogs: () => void;
  onOpenOutputFolder: () => void;
  theme: 'light' | 'dark';
  onToggleTheme: (e?: React.SyntheticEvent) => void;
  serverStatus: ServerStatusInfo | null;
  isExtracting: boolean;
  isTransitioning?: boolean;
}

export const TopNavBar: React.FC<TopNavBarProps> = ({
  currentTab,
  onSelectTab,
  engineSettings,
  onToggleServer,
  onOpenServerLogs,
  onOpenOutputFolder,
  theme,
  onToggleTheme,
  serverStatus,
  isExtracting,
  isTransitioning = false,
}) => {
  const currentStatus: 'offline' | 'starting' | 'ready' | 'error' =
    serverStatus?.status || (engineSettings.status === 'running' ? 'ready' : 'offline');

  const isServerRunning = currentStatus === 'ready';

  const statusConfig = {
    ready: {
      label: 'Local Engine Ready',
      wrapperClass:
        'bg-[#15803D]/10 dark:bg-[var(--success)]/10 border-[#15803D]/25 dark:border-[var(--success)]/25 text-[#14532D] dark:text-[var(--success)]',
      dotClass: 'bg-[#15803D] dark:bg-[var(--success)]',
    },
    starting: {
      label: 'Engine Starting...',
      wrapperClass:
        'bg-amber-500/10 dark:bg-amber-500/10 border-amber-500/25 dark:border-amber-500/25 text-amber-600 dark:text-amber-400',
      dotClass: 'bg-amber-500 dark:bg-amber-400 animate-pulse',
    },
    error: {
      label: 'Engine Error',
      wrapperClass:
        'bg-red-500/10 dark:bg-[var(--danger)]/10 border-red-500/25 dark:border-[var(--danger)]/25 text-red-700 dark:text-[var(--danger)]',
      dotClass: 'bg-red-500 dark:bg-[var(--danger)]',
    },
    offline: {
      label: 'Engine Offline',
      wrapperClass:
        'bg-[#DC2626]/10 dark:bg-[var(--danger)]/10 border-[#DC2626]/25 dark:border-[var(--danger)]/25 text-[#991B1B] dark:text-[var(--danger)]',
      dotClass: 'bg-[#DC2626] dark:bg-[var(--danger)]',
    },
  }[currentStatus];

  let buttonDisabled = false;
  let buttonTitle = '';
  let buttonAriaLabel = '';
  let buttonText = 'Stop Server';

  if (isServerRunning) {
    if (serverStatus?.ownership === 'external') {
      buttonDisabled = true;
      buttonTitle = `Server managed externally (PID ${serverStatus.pid || 'external'})`;
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
    <header className="h-12 w-full bg-[#F6F4EE] dark:bg-[var(--bg-surface)] border-b border-[#8A94A6]/30 dark:border-[var(--border)] flex items-center justify-between px-4 select-none shrink-0 z-20 transition-colors">
      {/* Left: Brand / Logotype & Navigation */}
      <div className="flex items-center gap-6">
        <button 
          className="flex flex-col text-left cursor-pointer group focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none rounded-sm active:scale-[0.98] active:translate-y-px transition-all duration-100 ease-out"
          onClick={() => onSelectTab('workspace')}
          type="button"
          aria-label="AksaraSight"
        >
          <span className="font-serif-brand text-[20px] font-semibold text-[#14213D] dark:text-[var(--text-1)] tracking-tight group-hover:text-[#0F766E] dark:group-hover:text-[var(--accent)] transition-colors leading-tight">
            AksaraSight
          </span>
          <span className="text-xs font-medium text-[#5A6478] dark:text-[var(--text-2)] tracking-normal leading-none mt-0.5">
            Local Archival & Document OCR
          </span>
        </button>

        <div className="h-6 w-px bg-[#8A94A6]/25 dark:bg-[var(--border)] hidden sm:block" aria-hidden="true" />

        <nav className="flex items-center gap-5 h-12 pt-3" aria-label="Main Navigation">
          <button
            onClick={() => onSelectTab('workspace')}
            className={`text-[13.5px] font-semibold pb-2.5 px-0.5 inline-flex items-center active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none rounded-xs ${
              currentTab === 'workspace'
                ? 'text-[#14213D] dark:text-[var(--text-1)] border-b-2 border-[#0F766E] dark:border-[var(--accent)]'
                : 'text-[#5A6478] dark:text-[var(--text-2)] hover:text-[#14213D] hover:dark:text-[var(--text-1)] border-b-2 border-transparent'
            }`}
          >
            Workspace
          </button>
          <button
            onClick={() => onSelectTab('settings')}
            className={`text-[13.5px] font-semibold pb-2.5 px-0.5 inline-flex items-center active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none rounded-xs ${
              currentTab === 'settings'
                ? 'text-[#14213D] dark:text-[var(--text-1)] border-b-2 border-[#0F766E] dark:border-[var(--accent)]'
                : 'text-[#5A6478] dark:text-[var(--text-2)] hover:text-[#14213D] hover:dark:text-[var(--text-1)] border-b-2 border-transparent'
            }`}
          >
            Settings
          </button>
        </nav>
      </div>

      {/* Right: Engine Status Indicator, Server Controls, Server Logs, Output Folder, Uiverse Theme Switch */}
      <div className="flex items-center gap-2 sm:gap-2.5">
        {/* Engine status indicator with high contrast and text label */}
        <div
          className={`flex items-center gap-2 px-2.5 h-8 rounded-lg border select-none transition-colors ${statusConfig.wrapperClass}`}
          role="status"
          aria-live="polite"
        >
          <span
            className={`inline-block w-2 h-2 rounded-full ${statusConfig.dotClass}`}
            aria-hidden="true"
          />
          <span className="font-semibold text-[12px] whitespace-nowrap tracking-tight">
            {statusConfig.label}
          </span>
          {serverStatus?.pid != null && (
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-black/5 dark:bg-white/10 font-medium">
              PID {serverStatus.pid}
            </span>
          )}
          {isServerRunning && (
            <span className="text-[11px] text-[#0F766E] dark:text-[var(--text-2)] font-medium hidden md:inline">
              · GLM-OCR
            </span>
          )}
        </div>

        {/* Start / Stop Server Toggle Button */}
        {isServerRunning ? (
          <button
            type="button"
            onClick={buttonDisabled ? undefined : onToggleServer}
            disabled={buttonDisabled}
            className={`h-8 w-8 sm:w-[108px] rounded-lg border border-[var(--danger)]/30 text-[var(--danger)] flex items-center justify-center gap-1.5 text-[12px] font-semibold active:scale-[0.96] active:translate-y-px active:brightness-95 transition-all duration-150 ease-out shadow-2xs focus-visible:ring-2 focus-visible:ring-[var(--danger)] focus-visible:outline-none shrink-0 ${
              buttonDisabled
                ? 'cursor-not-allowed opacity-50'
                : 'hover:border-[var(--danger)]/60 bg-[var(--danger)]/8 hover:bg-[var(--danger)]/15 cursor-pointer'
            }`}
            aria-label={buttonAriaLabel}
            title={buttonTitle}
          >
            <Square className="w-3.5 h-3.5 fill-current shrink-0" aria-hidden="true" />
            <span className="hidden sm:inline whitespace-nowrap">{buttonText}</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={buttonDisabled ? undefined : onToggleServer}
            disabled={buttonDisabled}
            className={`h-8 w-8 sm:w-[108px] rounded-lg bg-[#0F766E] text-white flex items-center justify-center gap-1.5 text-[12px] font-semibold active:scale-[0.96] active:translate-y-px active:brightness-95 transition-all duration-150 ease-out shadow-xs focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none shrink-0 ${
              buttonDisabled
                ? 'cursor-not-allowed opacity-50'
                : 'hover:bg-[#115E59] active:bg-[#0d4f4b] cursor-pointer'
            }`}
            aria-label={buttonAriaLabel}
            title={buttonTitle}
          >
            <Play className="w-3.5 h-3.5 fill-current shrink-0" aria-hidden="true" />
            <span className="hidden sm:inline whitespace-nowrap">{buttonText}</span>
          </button>
        )}

        {/* Server Logs Button */}
        <button
          type="button"
          onClick={onOpenServerLogs}
          className="h-8 px-2.5 rounded-lg border border-[#8A94A6] dark:border-[var(--border)] hover:border-[#14213D] dark:hover:border-[var(--border-strong)] bg-white/70 dark:bg-[var(--bg-elevated)] hover:bg-white hover:dark:bg-[var(--bg-active)] text-[#14213D] dark:text-[var(--text-1)] flex items-center gap-1.5 text-[12px] font-medium active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out cursor-pointer shadow-2xs focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none"
          title="View ServerManager logs"
          aria-label="Server Logs"
        >
          <Terminal className="w-4 h-4 text-[#5A6478] dark:text-[var(--text-2)]" aria-hidden="true" />
          <span className="hidden lg:inline">Server Logs</span>
        </button>

        {/* Local Output Folder Button */}
        <button
          onClick={onOpenOutputFolder}
          className="h-8 px-3 rounded-lg border border-[#8A94A6] dark:border-[var(--border)] hover:border-[#14213D] dark:hover:border-[var(--border-strong)] bg-white/70 dark:bg-[var(--bg-elevated)] hover:bg-white hover:dark:bg-[var(--bg-active)] text-[#14213D] dark:text-[var(--text-1)] active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out flex items-center gap-1.5 text-[12px] font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0F766E] cursor-pointer shadow-2xs"
          type="button"
          aria-label="Output Folder"
          title="Local disk folder: C:\Users\Fradana\Documents\AksaraSight\output"
        >
          <FolderOpen className="w-4 h-4 text-[#0F766E] dark:text-[var(--accent)]" aria-hidden="true" />
          <span className="hidden md:inline">Output Folder</span>
        </button>

        <div className="h-5 w-px bg-[#8A94A6]/30 dark:bg-[var(--border)] mx-0.5" aria-hidden="true" />

        {/* Uiverse Gentle Goat 72 Theme Switch */}
        <div className="flex items-center" title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>
          <input
            type="checkbox"
            className="theme-checkbox"
            checked={theme === 'dark'}
            onChange={(e) => onToggleTheme(e)}
            aria-label="Toggle dark mode"
          />
        </div>
      </div>
    </header>
  );
};
