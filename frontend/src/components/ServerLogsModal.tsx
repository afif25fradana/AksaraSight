import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Terminal, X, Copy, Check, Search, ArrowDown } from 'lucide-react';
import { ServerStatusInfo } from '../types';

interface ServerLogsModalProps {
  isOpen: boolean;
  onClose: () => void;
  serverStatus: ServerStatusInfo | null;
  onToggleServer?: () => void;
}

// Helper to parse timestamp, log level tag, and body
const parseLogLine = (line: string) => {
  const match = line.match(/^(\[\d{4}-\d{2}-\d{2}\s[^\]]+\])\s*(\[(?:INFO|HEALTH|OCR|WARN|ERROR)\])? ?(.*)$/);
  if (!match) {
    return {
      timestamp: null,
      tag: null,
      body: line,
    };
  }
  return {
    timestamp: match[1],
    tag: match[2] || null,
    body: match[3] || '',
  };
};

export const ServerLogsModal: React.FC<ServerLogsModalProps> = ({
  isOpen,
  onClose,
  serverStatus,
  onToggleServer,
}) => {
  const [filterText, setFilterText] = useState('');
  const [levelFilter, setLevelFilter] = useState<'ALL' | 'INFO' | 'HEALTH' | 'OCR' | 'WARN' | 'ERROR'>('ALL');
  const [autoScroll, setAutoScroll] = useState(true);
  const [copied, setCopied] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const logContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    const es = new EventSource('/api/server/logs/stream');

    const handleLog = (event: MessageEvent) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.line) {
          setLogs((prev) => {
            const next = [...prev, payload.line];
            return next.length > 500 ? next.slice(-500) : next;
          });
        }
      } catch {
        if (event.data) {
          setLogs((prev) => {
            const next = [...prev, event.data];
            return next.length > 500 ? next.slice(-500) : next;
          });
        }
      }
    };

    es.addEventListener('log', handleLog);
    es.onmessage = handleLog;

    return () => {
      es.close();
    };
  }, [isOpen]);

  const filteredLogs = useMemo(() => {
    return logs.filter((line) => {
      if (levelFilter !== 'ALL') {
        if (!line.includes(`[${levelFilter}]`)) return false;
      }
      if (filterText.trim()) {
        if (!line.toLowerCase().includes(filterText.toLowerCase())) return false;
      }
      return true;
    });
  }, [logs, levelFilter, filterText]);

  useEffect(() => {
    if (isOpen && autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [isOpen, autoScroll, filteredLogs]);

  const handleCopy = () => {
    navigator.clipboard.writeText(logs.join('\n'));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const statusBadge = useMemo(() => {
    const status = serverStatus?.status || 'offline';
    switch (status) {
      case 'ready':
        return {
          label: '● RUNNING :8080',
          className:
            'bg-[#0F766E]/10 dark:bg-[var(--success)]/10 text-[#0F766E] dark:text-[var(--success)] border-[#0F766E]/30 dark:border-[var(--success)]/30',
        };
      case 'starting':
        return {
          label: '○ STARTING',
          className:
            'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30',
        };
      case 'error':
        return {
          label: '○ ERROR',
          className:
            'bg-red-500/10 text-red-700 dark:text-[var(--danger)] border-red-500/30',
        };
      case 'offline':
      default:
        return {
          label: '○ OFFLINE',
          className:
            'bg-red-50 dark:bg-[var(--danger)]/10 text-red-700 dark:text-[var(--danger)] border-red-200 dark:border-[var(--danger)]/30',
        };
    }
  }, [serverStatus?.status]);

  const pidText = serverStatus?.pid
    ? `PID ${serverStatus.pid}`
    : serverStatus?.ownership === 'external'
    ? 'EXTERNAL'
    : 'NO PID';

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#14213D]/40 dark:bg-black/70 backdrop-blur-[4px] animate-modal-backdrop">
      <div 
        className="w-full max-w-4xl bg-[#FBFAF7] dark:bg-[var(--bg-surface)] border border-[#8A94A6]/30 dark:border-[var(--border)] text-[#14213D] dark:text-[var(--text-1)] rounded-xl shadow-2xl animate-modal-window will-change-transform overflow-hidden flex flex-col h-[85vh] max-h-[720px] transition-colors"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="server-logs-title"
      >
        {/* Header */}
        <div className="px-5 py-3.5 bg-[#FBFAF7] dark:bg-[var(--bg-surface)] border-b border-[#8A94A6]/25 dark:border-[var(--border)] text-[#14213D] dark:text-[var(--text-1)] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-[#0F766E]/10 dark:bg-[var(--accent)]/10 border border-[#0F766E]/20 dark:border-[var(--accent)]/30 flex items-center justify-center text-[#0F766E] dark:text-[var(--accent)]">
              <Terminal className="w-4.5 h-4.5" aria-hidden="true" />
            </div>
            <div>
              <h3 id="server-logs-title" className="font-['IBM_Plex_Sans',sans-serif] font-semibold text-[15px] text-[#14213D] dark:text-[var(--text-1)] flex items-center gap-2">
                Server Logs
                <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-black/[0.04] dark:bg-[var(--bg-base)] text-[#14213D] dark:text-[var(--text-1)] border border-black/10 dark:border-[var(--border)]">
                  {pidText}
                </span>
                <span className={`text-[11px] font-mono font-medium px-2 py-0.5 rounded border ${statusBadge.className}`}>
                  {statusBadge.label}
                </span>
              </h3>
              <p className="text-[12px] text-[#5A6478] dark:text-[var(--text-2)] mt-0.5">
                Live stdout / stderr from ServerManager ({logs.length} entries)
              </p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="w-8 h-8 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 text-[#5A6478] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)] flex items-center justify-center cursor-pointer transition-colors focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none active:scale-90 active:translate-y-px transition-transform duration-100 ease-out"
            aria-label="Close"
            type="button"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>

        {/* Toolbar: Search, Filters, Auto-scroll, Copy */}
        <div className="px-5 py-2.5 bg-[#FBFAF7] dark:bg-[var(--bg-elevated)] border-b border-[#8A94A6]/25 dark:border-[var(--border)] flex flex-wrap items-center justify-between gap-3 shrink-0 text-[12px]">
          <div className="flex items-center gap-2 flex-1 min-w-[200px]">
            <div className="relative flex-1 max-w-xs">
              <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-[#5A6478] dark:text-[var(--text-2)]" aria-hidden="true" />
              <input
                type="text"
                placeholder="Filter logs..."
                value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 bg-white dark:bg-[var(--bg-base)] border border-[#8A94A6]/35 dark:border-[var(--border)] text-[#14213D] dark:text-[var(--text-1)] placeholder-[#5A6478] dark:placeholder-[var(--text-3)] rounded-lg text-[12px] focus:outline-none focus:border-[#0F766E] dark:focus:border-[var(--accent)] focus:ring-1 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)] font-mono"
              />
            </div>
            <div className="flex items-center gap-1 bg-[#F0EEE8] dark:bg-[var(--bg-base)] p-0.5 rounded-lg border border-[#8A94A6]/25 dark:border-[var(--border)]">
              {(['ALL', 'INFO', 'HEALTH', 'OCR', 'WARN', 'ERROR'] as const).map((lvl) => (
                <button
                  key={lvl}
                  type="button"
                  onClick={() => setLevelFilter(lvl)}
                  className={`px-2 py-1 rounded text-[11px] font-mono cursor-pointer active:scale-95 active:translate-y-px transition-all duration-100 ease-out ${
                    levelFilter === lvl
                      ? 'bg-[#0F766E] dark:bg-[var(--accent)]/15 text-white dark:text-[var(--accent)] font-semibold shadow-2xs dark:shadow-none'
                      : 'text-[#5A6478] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)] hover:bg-black/5 dark:hover:bg-white/5'
                  }`}
                >
                  {lvl}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setAutoScroll(!autoScroll)}
              className={`px-2.5 py-1.5 rounded-lg border text-[11.5px] flex items-center gap-1 cursor-pointer transition-colors ${
                autoScroll
                  ? 'bg-[#0F766E]/10 dark:bg-[var(--accent)]/10 border-[#0F766E]/30 dark:border-[var(--accent)]/30 text-[#0F766E] dark:text-[var(--accent)] font-medium'
                  : 'border-[#8A94A6]/35 dark:border-[var(--border)] bg-white dark:bg-[var(--bg-elevated)] text-[#14213D] dark:text-[var(--text-1)] hover:bg-[#F0EEE8] dark:hover:bg-[var(--bg-active)]'
              }`}
            >
              <ArrowDown className="w-3 h-3" aria-hidden="true" />
              <span>Auto-scroll</span>
            </button>
            <button
              type="button"
              onClick={handleCopy}
              className="px-3 py-1.5 rounded-lg border border-[#8A94A6]/35 dark:border-[var(--border)] bg-white dark:bg-[var(--bg-elevated)] hover:bg-[#F0EEE8] dark:hover:bg-[var(--bg-active)] text-[#14213D] dark:text-[var(--text-1)] text-[11.5px] flex items-center gap-1.5 cursor-pointer active:scale-95 active:translate-y-px transition-all duration-100 ease-out"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-[#0F766E] dark:text-[var(--success)]" aria-hidden="true" />
                  <span className="text-[#0F766E] dark:text-[var(--success)] font-medium">Copied!</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5 text-[#5A6478] dark:text-[var(--text-2)]" aria-hidden="true" />
                  <span>Copy All</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Log Viewer Content */}
        <div className="flex-1 p-3.5 bg-[#FBFAF7] dark:bg-[var(--bg-surface)] min-h-0 flex flex-col">
          <div 
            ref={logContainerRef}
            className="flex-1 p-3.5 overflow-y-auto font-mono text-[11.5px] leading-relaxed bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#8A94A6]/25 dark:border-[var(--border)] text-[#14213D] dark:text-[var(--text-1)] rounded-lg space-y-0.5 select-text shadow-2xs"
          >
            {filteredLogs.length === 0 ? (
              <div className="text-[#5A6478] dark:text-[var(--text-2)] py-8 text-center italic">
                No logs matching "{filterText}"
              </div>
            ) : (
              filteredLogs.map((line, idx) => {
                const { timestamp, tag, body } = parseLogLine(line);
                return (
                  <div 
                    key={idx} 
                    className={`px-2 py-0.5 rounded transition-colors hover:bg-black/[0.03] dark:hover:bg-white/[0.04] flex items-baseline gap-2 ${
                      tag === '[WARN]' ? 'bg-amber-500/5 dark:bg-[var(--warning)]/10' : tag === '[ERROR]' ? 'bg-red-500/5 dark:bg-[var(--danger)]/10' : ''
                    }`}
                  >
                    {timestamp && (
                      <span className="text-[#5A6478] dark:text-[var(--text-3)] shrink-0 select-text">
                        {timestamp}
                      </span>
                    )}
                    {tag && (
                      <span className={`shrink-0 ${
                        tag === '[INFO]'
                          ? 'text-[#14213D] dark:text-[var(--text-1)] font-medium'
                          : tag === '[HEALTH]'
                          ? 'text-[#0F766E] dark:text-[var(--accent)] font-semibold'
                          : tag === '[OCR]'
                          ? 'text-[#0F766E] dark:text-[var(--accent)] font-medium'
                          : tag === '[WARN]'
                          ? 'text-[#B45309] dark:text-[var(--warning)] font-semibold'
                          : 'text-[#B91C1C] dark:text-[var(--danger)] font-semibold'
                      }`}>
                        {tag}
                      </span>
                    )}
                    <span className="text-[#14213D] dark:text-[var(--text-1)] break-all whitespace-pre-wrap">
                      {body}
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-[#8A94A6]/25 dark:border-[var(--border)] bg-[#FBFAF7] dark:bg-[var(--bg-surface)] flex items-center justify-between text-[11.5px] text-[#5A6478] dark:text-[var(--text-2)] shrink-0">
          <div>
            Showing {filteredLogs.length} of {logs.length} entries · In-memory log buffer (bounded) · No OCR text recorded
          </div>
          <button
            onClick={onClose}
            className="px-3.5 py-1.5 rounded-lg border border-[#8A94A6]/35 dark:border-[var(--border)] bg-white dark:bg-[var(--bg-elevated)] hover:bg-[#F0EEE8] dark:hover:bg-[var(--bg-active)] text-[#14213D] dark:text-[var(--text-1)] font-medium transition-colors cursor-pointer text-[12px]"
            type="button"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
