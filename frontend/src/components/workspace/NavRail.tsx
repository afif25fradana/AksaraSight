import React, { useEffect } from 'react';
import { Layers, ListOrdered, Settings, Terminal } from 'lucide-react';

export type NavRailTab = 'workspace' | 'settings';

export interface NavRailProps {
  activeTab: string;
  onSelectTab: (tab: NavRailTab) => void;
  onOpenServerLogs?: () => void;
  isQueueOpen?: boolean;
  onToggleQueue?: () => void;
}

export const NavRail: React.FC<NavRailProps> = ({
  activeTab,
  onSelectTab,
  onOpenServerLogs,
  isQueueOpen = true,
  onToggleQueue,
}) => {
  // Global keyboard shortcuts:
  // Ctrl+1 / Cmd+1: Workspace
  // Ctrl+, / Cmd+,: Settings
  // Ctrl+B / Cmd+B: Toggle File Queue
  // Ctrl+Shift+L / Cmd+Shift+L: Server Logs
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      const isModifier = e.ctrlKey || e.metaKey;
      if (!isModifier) return;

      if (e.shiftKey && e.key.toLowerCase() === 'l') {
        e.preventDefault();
        onOpenServerLogs?.();
      } else if (e.key === '1') {
        e.preventDefault();
        onSelectTab('workspace');
      } else if (e.key === ',') {
        e.preventDefault();
        onSelectTab('settings');
      } else if (e.key.toLowerCase() === 'b') {
        e.preventDefault();
        onToggleQueue?.();
      }
    };

    window.addEventListener('keydown', handleGlobalKeyDown);
    return () => window.removeEventListener('keydown', handleGlobalKeyDown);
  }, [onSelectTab, onToggleQueue, onOpenServerLogs]);

  return (
    <nav
      aria-label="Application Navigation"
      className="w-12 bg-[#202020] border-r border-white/8 flex flex-col justify-between py-2 shrink-0 select-none z-30 h-full"
    >
      {/* Upper Stack: AksaraSight App Mark + Workspace destination + Queue Disclosure */}
      <div className="flex flex-col items-center gap-2">
        {/* App Mark */}
        <div
          role="img"
          className="w-9 h-9 flex items-center justify-center rounded-sm text-[#60CDFF] mb-1"
          title="AksaraSight"
          aria-label="AksaraSight"
        >
          <svg
            className="w-5 h-5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M4 4C4 2.89543 4.89543 2 6 2H14L20 8V20C20 21.1046 19.1046 22 18 22H6C4.89543 22 4 21.1046 4 20V4Z" />
            <path d="M14 2V8H20" />
            <path d="M8 13H16" />
            <path d="M8 17H13" />
          </svg>
        </div>

        {/* Workspace Destination Button */}
        <button
          type="button"
          onClick={() => onSelectTab('workspace')}
          aria-current={activeTab === 'workspace' ? 'page' : undefined}
          title="Workspace (Ctrl+1)"
          aria-label="Workspace"
          className={`relative w-10 h-10 flex items-center justify-center rounded-sm transition-colors duration-100 ease-out cursor-pointer ${
            activeTab === 'workspace'
              ? 'bg-white/[0.08] text-[#F3F3F3]'
              : 'text-[#A6A6A6] hover:text-[#F3F3F3] hover:bg-white/[0.05]'
          } focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:ring-offset-1 focus-visible:ring-offset-[#202020]`}
        >
          {activeTab === 'workspace' && (
            <span
              className="w-[3px] h-4 rounded-full bg-[#60CDFF] absolute left-1 animate-pill-enter"
              aria-hidden="true"
              data-testid="active-indicator"
            />
          )}
          <Layers className="w-5 h-5" aria-hidden="true" />
        </button>

        {/* Standalone Queue Panel Disclosure Button */}
        <button
          type="button"
          aria-expanded={isQueueOpen}
          aria-controls="workspace-file-queue"
          aria-label={isQueueOpen ? 'Collapse File Queue' : 'Expand File Queue'}
          title={isQueueOpen ? 'Collapse Queue (Ctrl+B)' : 'Expand Queue (Ctrl+B)'}
          onClick={onToggleQueue}
          className={`w-10 h-10 flex items-center justify-center rounded-sm transition-colors duration-100 ease-out cursor-pointer ${
            isQueueOpen && activeTab === 'workspace'
              ? 'text-[#60CDFF] bg-white/[0.05]'
              : 'text-[#A6A6A6] hover:text-[#F3F3F3] hover:bg-white/[0.05]'
          } focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:ring-offset-1 focus-visible:ring-offset-[#202020]`}
        >
          <ListOrdered className="w-5 h-5" aria-hidden="true" />
        </button>
      </div>

      {/* Lower Stack: Server Logs Action Button + Settings Destination Button */}
      <div className="flex flex-col items-center gap-1 w-full">
        <button
          type="button"
          onClick={onOpenServerLogs}
          aria-haspopup="dialog"
          title="Server Logs (Ctrl+Shift+L)"
          aria-label="Server Logs"
          className="w-10 h-10 flex items-center justify-center rounded-sm text-[#A6A6A6] hover:text-[#F3F3F3] hover:bg-white/[0.05] transition-colors duration-100 ease-out cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:ring-offset-1 focus-visible:ring-offset-[#202020]"
        >
          <Terminal className="w-5 h-5" aria-hidden="true" />
        </button>

        <button
          type="button"
          onClick={() => onSelectTab('settings')}
          aria-current={activeTab === 'settings' ? 'page' : undefined}
          title="Settings (Ctrl+,)"
          aria-label="Settings"
          className={`relative w-10 h-10 flex items-center justify-center rounded-sm transition-colors duration-100 ease-out cursor-pointer ${
            activeTab === 'settings'
              ? 'bg-white/[0.08] text-[#F3F3F3]'
              : 'text-[#A6A6A6] hover:text-[#F3F3F3] hover:bg-white/[0.05]'
          } focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:ring-offset-1 focus-visible:ring-offset-[#202020]`}
        >
          {activeTab === 'settings' && (
            <span
              className="w-[3px] h-4 rounded-full bg-[#60CDFF] absolute left-1 animate-pill-enter"
              aria-hidden="true"
              data-testid="active-indicator"
            />
          )}
          <Settings className="w-5 h-5" aria-hidden="true" />
        </button>
      </div>
    </nav>
  );
};
