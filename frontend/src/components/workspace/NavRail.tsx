import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Layers, ListOrdered, Settings, Terminal } from 'lucide-react';

export type NavRailTab = 'workspace' | 'settings';

export interface NavRailProps {
  activeTab: string;
  onSelectTab: (tab: NavRailTab) => void;
  onOpenServerLogs?: () => void;
  isQueueOpen?: boolean;
  onToggleQueue?: () => void;
}

interface TabItem {
  id: NavRailTab;
  label: string;
  shortcut?: string;
  icon: React.ReactNode;
}

const TABS: TabItem[] = [
  {
    id: 'workspace',
    label: 'Workspace',
    shortcut: 'Ctrl+1',
    icon: <Layers className="w-5 h-5" aria-hidden="true" />,
  },
  {
    id: 'settings',
    label: 'Settings',
    shortcut: 'Ctrl+,',
    icon: <Settings className="w-5 h-5" aria-hidden="true" />,
  },
];

export const NavRail: React.FC<NavRailProps> = ({
  activeTab,
  onSelectTab,
  onOpenServerLogs,
  isQueueOpen = true,
  onToggleQueue,
}) => {
  const [focusedIndex, setFocusedIndex] = useState(() => {
    const idx = TABS.findIndex((t) => t.id === activeTab);
    return idx >= 0 ? idx : 0;
  });
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  // Keep focusedIndex aligned when activeTab prop changes
  useEffect(() => {
    const idx = TABS.findIndex((t) => t.id === activeTab);
    if (idx >= 0) {
      setFocusedIndex(idx);
    }
  }, [activeTab]);

  // Global keyboard shortcuts: Ctrl+1 for Workspace, Ctrl+, for Settings, Ctrl+B for Queue
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      const isModifier = e.ctrlKey || e.metaKey;
      if (!isModifier) return;

      if (e.key === '1') {
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
  }, [onSelectTab, onToggleQueue]);

  // Roving Tabindex keyboard cycling for the 2 view tabs
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent, index: number) => {
      let nextIndex = index;

      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          nextIndex = (index + 1) % TABS.length;
          break;
        case 'ArrowUp':
          e.preventDefault();
          nextIndex = (index - 1 + TABS.length) % TABS.length;
          break;
        case 'Home':
          e.preventDefault();
          nextIndex = 0;
          break;
        case 'End':
          e.preventDefault();
          nextIndex = TABS.length - 1;
          break;
        case 'Enter':
        case ' ':
          e.preventDefault();
          onSelectTab(TABS[index].id);
          return;
        default:
          return;
      }

      setFocusedIndex(nextIndex);
      tabRefs.current[nextIndex]?.focus();
      onSelectTab(TABS[nextIndex].id);
    },
    [onSelectTab]
  );

  return (
    <nav
      aria-label="Application Navigation"
      className="w-12 bg-[#202020] border-r border-white/8 flex flex-col justify-between py-2 shrink-0 select-none z-30 h-full"
    >
      {/* Upper Stack: AksaraSight App Mark + View Tabs + Queue Disclosure */}
      <div className="flex flex-col items-center gap-2">
        {/* App Mark */}
        <div
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

        {/* WAI-ARIA Vertical Tablist (owns Workspace and Settings only) */}
        <div
          role="tablist"
          aria-orientation="vertical"
          aria-label="Views"
          className="flex flex-col items-center gap-1 w-full"
        >
          {TABS.map((tab, idx) => {
            const isActive = tab.id === activeTab;
            const isFocused = idx === focusedIndex;

            return (
              <button
                key={tab.id}
                ref={(el) => {
                  tabRefs.current[idx] = el;
                }}
                role="tab"
                id={`nav-tab-${tab.id}`}
                aria-selected={isActive}
                aria-controls={`nav-panel-${tab.id}`}
                tabIndex={isFocused ? 0 : -1}
                onClick={() => {
                  setFocusedIndex(idx);
                  onSelectTab(tab.id);
                }}
                onKeyDown={(e) => handleKeyDown(e, idx)}
                title={tab.shortcut ? `${tab.label} (${tab.shortcut})` : tab.label}
                aria-label={tab.label}
                className={`relative w-10 h-10 flex items-center justify-center rounded-sm transition-colors duration-100 ease-out cursor-pointer ${
                  isActive
                    ? 'bg-white/[0.08] text-[#F3F3F3]'
                    : 'text-[#A6A6A6] hover:text-[#F3F3F3] hover:bg-white/[0.05]'
                } focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:ring-offset-1 focus-visible:ring-offset-[#202020]`}
              >
                {/* 3px vertical active indicator pill */}
                {isActive && (
                  <span
                    className="w-[3px] h-4 rounded-full bg-[#60CDFF] absolute left-1"
                    aria-hidden="true"
                    data-testid="active-indicator"
                  />
                )}
                {tab.icon}
              </button>
            );
          })}
        </div>

        {/* Divider between view tabs and queue panel disclosure */}
        <div className="w-6 h-px bg-white/10 my-0.5" aria-hidden="true" />

        {/* Standalone Queue Panel Disclosure Button (Outside tablist) */}
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

      {/* Lower Stack: Server Logs */}
      <div className="flex flex-col items-center gap-1 w-full">
        <button
          type="button"
          onClick={onOpenServerLogs}
          title="Server Logs"
          aria-label="Server Logs"
          className="w-10 h-10 flex items-center justify-center rounded-sm text-[#A6A6A6] hover:text-[#F3F3F3] hover:bg-white/[0.05] transition-colors duration-100 ease-out cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:ring-offset-1 focus-visible:ring-offset-[#202020]"
        >
          <Terminal className="w-5 h-5" aria-hidden="true" />
        </button>
      </div>
    </nav>
  );
};
