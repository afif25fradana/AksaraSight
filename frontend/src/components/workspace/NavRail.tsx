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
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.tagName === 'SELECT' ||
          target.isContentEditable ||
          target.getAttribute?.('contenteditable') === 'true' ||
          target.getAttribute?.('contenteditable') === '')
      ) {
        return;
      }

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
          className="w-9 h-9 flex items-center justify-center rounded-sm mb-1"
          title="AksaraSight"
          aria-label="AksaraSight"
        >
          <svg
            className="w-7 h-7"
            viewBox="0 0 512 512"
            fill="none"
            aria-hidden="true"
          >
            <g transform="translate(256 256) scale(1.12) translate(-256 -256)">
              <circle cx="320.38" cy="258.68" r="48.83" fill="#0091E6" />
              <path
                d="M 272.03 265.49 Q 320.38 246.96 368.73 265.49 A 48.83 48.83 0 0 1 272.03 265.49 Z"
                fill="#60CDFF"
              />
              <circle cx="320.40" cy="259.03" r="23.86" fill="#181818" />
              <circle cx="336.13" cy="243.87" r="11.30" fill="#F3F3F3" />
              <path
                d="M 350.20 198.35 C 325.88 194.05 302.30 194.88 278.97 203.67 C 263.93 209.33 250.62 217.85 236.60 225.50 C 220.08 234.51 201.64 242.58 183.06 245.99 C 189.80 229.82 199.00 213.71 207.95 198.50 C 219.18 179.41 231.61 159.93 249.33 146.21 C 246.05 153.59 241.42 161.30 237.73 168.86 C 230.77 183.16 219.49 212.05 218.60 227.52 C 228.53 226.03 239.51 218.49 247.78 212.63 C 250.57 203.04 252.96 193.23 256.32 183.76 C 260.20 172.87 265.31 162.49 270.35 152.10 C 272.89 146.86 275.70 141.73 278.72 136.74 C 281.60 131.99 285.09 128.12 286.26 122.77 C 271.68 112.46 247.54 128.22 235.98 137.79 C 200.08 167.52 180.01 211.57 156.22 250.49 C 148.99 252.07 141.60 252.80 134.33 254.19 C 107.96 259.23 77.09 267.96 60.80 291.15 C 46.67 311.26 45.75 343.75 73.04 353.12 C 77.18 354.54 81.70 355.14 86.07 355.08 C 107.38 354.76 124.17 339.37 137.08 324.05 C 152.74 305.48 162.79 283.40 174.99 262.75 C 192.62 259.08 209.61 255.26 226.20 248.05 C 249.63 237.88 271.53 224.10 296.50 217.78 C 317.48 212.46 340.43 215.30 360.28 223.43 C 375.53 229.68 389.68 239.11 402.18 249.76 C 412.78 258.78 422.76 269.81 427.62 283.08 C 438.24 312.11 422.93 344.67 398.15 360.95 C 346.76 394.71 262.04 376.87 246.84 311.63 C 259.62 317.40 272.18 323.42 285.95 326.66 C 319.84 334.63 353.88 326.77 381.86 306.42 C 390.19 300.35 397.71 293.34 404.32 285.41 C 406.85 282.37 410.36 278.54 411.55 274.70 C 411.82 273.83 411.39 273.07 411.50 272.37 C 410.80 272.49 410.07 271.88 409.17 272.19 C 405.27 273.56 399.69 280.16 396.13 282.90 C 387.40 289.60 378.16 295.38 368.20 300.09 C 323.51 321.19 276.08 311.37 241.26 276.87 C 240.77 267.28 242.92 256.86 241.72 247.70 C 232.59 249.45 222.64 254.54 214.26 258.72 C 210.98 298.05 221.85 338.18 252.90 364.35 C 291.77 397.12 351.95 400.48 397.68 381.41 C 419.51 372.31 439.86 357.17 451.02 335.84 C 465.91 307.41 463.79 277.14 444.97 251.11 C 438.11 241.61 429.20 233.94 420.03 226.76 C 400.48 211.44 367.11 192.40 370.96 163.12 C 371.78 156.88 373.74 150.81 377.83 145.90 C 387.89 133.82 410.69 128.56 423.29 139.78 C 433.11 148.54 432.46 167.05 420.03 173.20 C 412.97 176.70 411.41 173.84 405.14 173.58 C 404.42 173.55 403.78 174.12 403.27 174.14 C 405.12 190.10 424.41 192.49 436.33 185.55 C 460.52 171.46 453.41 136.04 430.43 124.92 C 399.23 109.83 355.51 125.09 345.89 159.71 C 342.06 173.49 345.98 185.42 350.20 198.35 Z M 147.53 266.79 C 136.04 286.80 119.97 312.76 101.59 326.78 C 93.79 332.73 80.55 339.50 71.82 331.28 C 62.18 322.20 69.69 305.42 76.77 297.36 C 92.28 279.70 124.36 267.59 147.53 266.79 Z"
                fill="#F3F3F3"
                fillRule="evenodd"
              />
            </g>
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
