import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Terminal, X, Copy, Check, Search, ArrowDown } from 'lucide-react';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { ServerStatusInfo } from '../../types';

interface ServerLogsModalProps {
  isOpen: boolean;
  onClose: () => void;
  serverStatus: ServerStatusInfo | null;
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
}) => {
  const [filterText, setFilterText] = useState('');
  const [levelFilter, setLevelFilter] = useState<'ALL' | 'INFO' | 'HEALTH' | 'OCR' | 'WARN' | 'ERROR'>('ALL');
  const [autoScroll, setAutoScroll] = useState(true);
  const [copied, setCopied] = useState(false);
  const copyTimerRef = useRef<NodeJS.Timeout | number | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const logContainerRef = useRef<HTMLDivElement>(null);
  const [isRendered, setIsRendered] = useState(isOpen);
  const [isClosing, setIsClosing] = useState(false);
  const modalRef = useFocusTrap<HTMLDivElement>(isRendered);

  useEffect(() => {
    if (isOpen) {
      setIsRendered(true);
      setIsClosing(false);
    } else if (isRendered) {
      setIsClosing(true);
      const timer = setTimeout(() => {
        setIsRendered(false);
        setIsClosing(false);
      }, 150);
      return () => clearTimeout(timer);
    }
  }, [isOpen, isRendered]);

  useEffect(() => {
    return () => {
      if (copyTimerRef.current) {
        clearTimeout(copyTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!isOpen) return;

    const es = new EventSource('/api/server/logs/stream');

    const handleLog = (event: MessageEvent) => {
      try {
        let payload = JSON.parse(event.data);
        if (typeof payload === 'string') {
          try {
            payload = JSON.parse(payload);
          } catch {}
        }
        const line = typeof payload === 'object' && payload !== null ? payload.line : payload;
        if (line) {
          setLogs((prev) => {
            const next = [...prev, String(line)];
            return next.length > 500 ? next.slice(-500) : next;
          });
        }
      } catch {
        if (event.data) {
          setLogs((prev) => {
            const next = [...prev, String(event.data)];
            return next.length > 500 ? next.slice(-500) : next;
          });
        }
      }
    };

    es.addEventListener('log', handleLog);
    es.onmessage = handleLog;
    es.onerror = (err) => {
      console.warn('Server logs SSE interrupted, auto-reconnecting:', err);
    };

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
    if (copyTimerRef.current) {
      clearTimeout(copyTimerRef.current);
    }
    copyTimerRef.current = setTimeout(() => {
      setCopied(false);
      copyTimerRef.current = null;
    }, 2000);
  };

  const statusBadge = useMemo(() => {
    const status = String(serverStatus?.status || 'offline').toLowerCase();
    switch (status) {
      case 'ready':
        return {
          label: '● RUNNING :8080',
          className:
            'bg-[#78c697]/15 text-[#78c697] border-[#78c697]/30',
        };
      case 'starting':
        return {
          label: '○ STARTING',
          className:
            'bg-amber-500/15 text-amber-300 border-amber-500/30',
        };
      case 'error':
        return {
          label: '○ ERROR',
          className:
            'bg-red-500/15 text-[#e58383] border-red-500/30',
        };
      case 'offline':
      default:
        return {
          label: '○ OFFLINE',
          className:
            'bg-red-500/15 text-[#e58383] border-red-500/30',
        };
    }
  }, [serverStatus?.status]);

  const pidText = serverStatus?.pid
    ? `PID ${serverStatus.pid}`
    : String(serverStatus?.ownership || '').toLowerCase() === 'external'
    ? 'EXTERNAL'
    : 'NO PID';

  if (!isRendered) return null;

  return (
    <div 
      className={`fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-[4px] ${
        isClosing ? 'opacity-0 transition-opacity duration-150 ease-tactile pointer-events-none' : 'animate-modal-backdrop'
      }`}
      onClick={onClose}
    >
      <div 
        ref={modalRef}
        className={`w-full max-w-4xl bg-[#272727] border border-white/[0.08] text-[#F3F3F3] rounded-lg shadow-xs will-change-transform overflow-hidden flex flex-col h-[85vh] max-h-[720px] transition-colors ${
          isClosing ? 'animate-modal-window-exit' : 'animate-modal-window'
        }`}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="server-logs-title"
      >
        {/* Header */}
        <div className="px-5 py-3.5 bg-[#272727] border-b border-white/[0.04] text-[#F3F3F3] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-md bg-[#60CDFF]/10 border border-[#60CDFF]/20 flex items-center justify-center text-[#60CDFF]">
              <Terminal className="w-4.5 h-4.5" aria-hidden="true" />
            </div>
            <div>
              <h3 id="server-logs-title" className="font-sans font-semibold text-[15px] text-[#F3F3F3] flex items-center gap-2">
                Server Logs
                <span className="text-[11px] font-mono px-2 py-0.5 rounded-sm bg-[#202020] text-[#F3F3F3] border border-white/[0.06]">
                  {pidText}
                </span>
                <span className={`text-[11px] font-mono font-medium px-2 py-0.5 rounded-sm border ${statusBadge.className}`}>
                  {statusBadge.label}
                </span>
              </h3>
              <p className="text-[12px] text-[#A6A6A6] mt-0.5">
                Live stdout / stderr from ServerManager ({logs.length} entries)
              </p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="w-8 h-8 rounded-md hover:bg-white/5 text-[#A6A6A6] hover:text-[#F3F3F3] flex items-center justify-center cursor-pointer transition-colors focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none active:scale-90 active:translate-y-px transition-transform duration-100 ease-out"
            aria-label="Close"
            type="button"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>

        {/* Toolbar: Search, Filters, Auto-scroll, Copy */}
        <div className="px-5 py-2.5 bg-[#2D2D2D] border-b border-white/[0.04] flex flex-wrap items-center justify-between gap-3 shrink-0 text-[12px]">
          <div className="flex items-center gap-2 flex-1 min-w-[200px]">
            <div className="relative flex-1 max-w-xs">
              <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-[#929292]" aria-hidden="true" />
              <input
                type="text"
                placeholder="Filter logs..."
                aria-label="Filter logs"
                value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 bg-[#202020] border border-white/[0.06] text-[#F3F3F3] placeholder-[#929292] rounded-md text-[12px] focus:outline-none focus:border-[#60CDFF] focus:ring-1 focus:ring-[#60CDFF] font-mono"
              />
            </div>
            <div className="flex items-center gap-1 bg-[#202020] p-0.5 rounded-md border border-white/[0.04]">
              {(['ALL', 'INFO', 'HEALTH', 'OCR', 'WARN', 'ERROR'] as const).map((lvl) => (
                <button
                  key={lvl}
                  type="button"
                  onClick={() => setLevelFilter(lvl)}
                  className={`px-2 py-1 rounded-sm text-[11px] font-mono cursor-pointer active:scale-95 active:translate-y-px transition-all duration-100 ease-out focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none ${
                    levelFilter === lvl
                      ? 'bg-[#60CDFF] text-[#000000] font-semibold'
                      : 'text-[#A6A6A6] hover:text-[#F3F3F3] hover:bg-white/5'
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
              className={`px-2.5 py-1.5 rounded-md border text-[11.5px] flex items-center gap-1 cursor-pointer transition-colors focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none ${
                autoScroll
                  ? 'bg-[#60CDFF]/15 border-[#60CDFF]/30 text-[#60CDFF] font-medium'
                  : 'border-white/[0.08] bg-[#202020] text-[#A6A6A6] hover:text-[#F3F3F3]'
              }`}
            >
              <ArrowDown className="w-3 h-3" aria-hidden="true" />
              <span>Auto-scroll</span>
            </button>
            <button
              type="button"
              onClick={handleCopy}
              className="px-3 py-1.5 rounded-md border border-white/[0.08] bg-[#202020] hover:bg-white/5 text-[#F3F3F3] text-[11.5px] flex items-center gap-1.5 cursor-pointer active:scale-95 active:translate-y-px transition-all duration-100 ease-out focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-[#78c697]" aria-hidden="true" />
                  <span className="text-[#78c697] font-medium">Copied!</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5 text-[#A6A6A6]" aria-hidden="true" />
                  <span>Copy All</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Log Viewer Content */}
        <div className="flex-1 p-3.5 bg-[#272727] min-h-0 flex flex-col">
          <div 
            ref={logContainerRef}
            className="flex-1 p-3.5 overflow-y-auto font-mono text-[11.5px] leading-relaxed bg-[#202020] border border-white/[0.04] text-[#F3F3F3] rounded-md space-y-0.5 select-text shadow-xs"
          >
            {filteredLogs.length === 0 ? (
              <div className="text-[#A6A6A6] py-8 text-center italic">
                {logs.length === 0
                  ? 'Waiting for engine server logs...'
                  : `No logs matching "${filterText}"`}
              </div>
            ) : (
              filteredLogs.map((line, idx) => {
                const { timestamp, tag, body } = parseLogLine(line);
                return (
                  <div 
                    key={idx} 
                    className={`px-2 py-0.5 rounded transition-colors hover:bg-white/[0.03] flex items-baseline gap-2 ${
                      tag === '[WARN]' ? 'bg-amber-500/10' : tag === '[ERROR]' ? 'bg-red-500/10' : ''
                    }`}
                  >
                    {timestamp && (
                      <span className="text-[#929292] shrink-0 select-text">
                        {timestamp}
                      </span>
                    )}
                    {tag && (
                      <span className={`shrink-0 ${
                        tag === '[INFO]'
                          ? 'text-[#F3F3F3] font-medium'
                          : tag === '[HEALTH]'
                          ? 'text-[#60CDFF] font-semibold'
                          : tag === '[OCR]'
                          ? 'text-[#60CDFF] font-medium'
                          : tag === '[WARN]'
                          ? 'text-[#e0a96d] font-semibold'
                          : 'text-[#e58383] font-semibold'
                      }`}>
                        {tag}
                      </span>
                    )}
                    <span className="text-[#F3F3F3] break-all whitespace-pre-wrap">
                      {body}
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-white/[0.04] bg-[#272727] flex items-center justify-between text-[11.5px] text-[#A6A6A6] shrink-0">
          <div>
            Showing {filteredLogs.length} of {logs.length} entries · In-memory log buffer (bounded) · No OCR text recorded
          </div>
          <button
            onClick={onClose}
            className="px-3.5 py-1.5 rounded-md border border-white/[0.08] hover:border-white/[0.16] bg-[#2D2D2D] text-[#F3F3F3] font-medium transition-colors cursor-pointer text-[12px] focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
            type="button"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
