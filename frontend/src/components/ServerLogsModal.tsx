import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Terminal, X, Copy, Check, Search, ArrowDown } from 'lucide-react';

interface ServerLogsModalProps {
  isOpen: boolean;
  onClose: () => void;
  isEngineRunning: boolean;
}

// Generate realistic 200 lines of ServerManager / llama-server logs
const generateInitialLogs = (): string[] => {
  const baseTime = new Date(Date.now() - 3600000); // 1 hour ago
  const formatTime = (offsetSec: number) => {
    const d = new Date(baseTime.getTime() + offsetSec * 1000);
    return `${d.toISOString().slice(0, 10)} ${d.toTimeString().slice(0, 8)}.${String(d.getMilliseconds()).padStart(3, '0')}`;
  };

  const logs: string[] = [
    `[${formatTime(0)}] [INFO] [ServerManager] Initializing AksaraSight local engine runtime environment...`,
    `[${formatTime(1)}] [INFO] [Hardware] Probing host accelerators: CPU + GPU detected.`,
    `[${formatTime(1)}] [INFO] [Hardware] CPU: 12th Gen Intel(R) Core(TM) i7-12700H (14 cores, 20 threads)`,
    `[${formatTime(2)}] [INFO] [Hardware] GPU: NVIDIA GeForce RTX 3060 Laptop GPU (6144 MB VRAM)`,
    `[${formatTime(2)}] [INFO] [Hardware] CUDA driver version: 12.4 (Compute Capability 8.6, Arch: sm_86)`,
    `[${formatTime(3)}] [INFO] [Hardware] Acceleration recommendation: CUDA (Full GPU offload supported)`,
    `[${formatTime(4)}] [INFO] [RuntimeManager] Selected runtime mode: managed (target: b10930-cuda)`,
    `[${formatTime(5)}] [INFO] [RuntimeManager] Verified executable: C:\\Users\\Fradana\\AppData\\Local\\AksaraSight\\runtimes\\b10930-cuda\\llama-server.exe`,
    `[${formatTime(6)}] [INFO] [RuntimeManager] SHA256 checksum verified for runtime binary.`,
    `[${formatTime(7)}] [INFO] [ServerManager] Resolving model weights: ggml-org/GLM-OCR-GGUF (Q4_K_M)`,
    `[${formatTime(8)}] [INFO] [ServerManager] Model path: C:\\Users\\Fradana\\.cache\\huggingface\\hub\\models--ggml-org--GLM-OCR-GGUF\\glm-ocr-q4_k_m.gguf`,
    `[${formatTime(9)}] [INFO] [ServerManager] mmproj path: C:\\Users\\Fradana\\.cache\\huggingface\\hub\\models--ggml-org--GLM-OCR-GGUF\\glm-ocr-mmproj-f16.gguf`,
    `[${formatTime(10)}] [INFO] [ServerManager] Spawning subprocess (PID 14288) with args:`,
    `[${formatTime(10)}] [INFO]   llama-server.exe --host 127.0.0.1 --port 8080 -m glm-ocr-q4_k_m.gguf --mmproj glm-ocr-mmproj-f16.gguf -ngl 99 -c 8192 --threads 8`,
    `[${formatTime(11)}] [INFO] [llama-server] build = 10930 (e4b29c1)`,
    `[${formatTime(11)}] [INFO] [llama-server] built with MSVC 19.38.32919.0 for x64 with CUDA 12.4`,
    `[${formatTime(12)}] [INFO] [llama-server] system info: n_threads = 8 / 20 | AVX = 1 | AVX2 = 1 | FMA = 1 | CUDA = 1 |`,
    `[${formatTime(13)}] [INFO] [llama-server] llama_model_loader: loaded meta data with 34 key-value pairs and 320 tensors from glm-ocr-q4_k_m.gguf`,
    `[${formatTime(14)}] [INFO] [llama-server] llama_model_loader: - kv   0: general.architecture                  str              = glm`,
    `[${formatTime(14)}] [INFO] [llama-server] llama_model_loader: - kv   1: general.type                          str              = model`,
    `[${formatTime(15)}] [INFO] [llama-server] llama_model_loader: - kv   2: general.name                          str              = GLM-OCR`,
    `[${formatTime(15)}] [INFO] [llama-server] llama_model_loader: - kv   3: glm.context_length                    u32              = 8192`,
    `[${formatTime(16)}] [INFO] [llama-server] llama_model_loader: - kv   4: glm.embedding_length                  u32              = 4096`,
    `[${formatTime(16)}] [INFO] [llama-server] llama_model_loader: - kv   5: glm.block_count                       u32              = 28`,
    `[${formatTime(17)}] [INFO] [llama-server] llm_load_tensors: offloading 28 repeating layers to GPU`,
    `[${formatTime(17)}] [INFO] [llama-server] llm_load_tensors: offloaded 28/28 layers to CUDA GPU`,
    `[${formatTime(18)}] [INFO] [llama-server] llm_load_tensors: CUDA buffer size = 3280.45 MiB`,
    `[${formatTime(19)}] [INFO] [llama-server] llm_load_tensors: host RAM buffer size = 124.12 MiB`,
    `[${formatTime(20)}] [INFO] [llama-server] clip_model_load: loading multimodal vision projector glm-ocr-mmproj-f16.gguf`,
    `[${formatTime(21)}] [INFO] [llama-server] clip_model_load: vision projector loaded successfully (148.20 MiB)`,
    `[${formatTime(22)}] [INFO] [llama-server] llama_init_from_model: kv self size  = 1024.00 MiB (CUDA)`,
    `[${formatTime(23)}] [INFO] [llama-server] llama_init_from_model: compute buffer = 256.00 MiB`,
    `[${formatTime(24)}] [INFO] [llama-server] main: HTTP server listening on http://127.0.0.1:8080`,
    `[${formatTime(25)}] [INFO] [llama-server] main: health endpoint active at http://127.0.0.1:8080/health`,
    `[${formatTime(26)}] [HEALTH] [ServerManager] Probe #1 -> GET http://127.0.0.1:8080/health HTTP/1.1 (status: ok) [200 OK, 12ms]`,
    `[${formatTime(27)}] [INFO] [ServerManager] Server state transition: STARTING -> READY`,
    `[${formatTime(28)}] [INFO] [Doctor] Running self-test: Multimodal vision 1x1 synthetic image probe...`,
    `[${formatTime(29)}] [INFO] [Doctor] POST /v1/chat/completions -> image probe returned valid tokens. Latency: 142ms.`,
    `[${formatTime(30)}] [INFO] [ServerManager] Health check verified. Engine ready for incoming OCR requests.`
  ];

  // Add realistic operational logs up to 200 lines
  let sec = 35;
  const docs = [
    { name: 'invoice-scan-03.pdf', pages: 3 },
    { name: 'surat-perjanjian-v2.pdf', pages: 12 },
    { name: 'arsip-kolonial-1892.png', pages: 8 },
  ];

  for (let i = 0; logs.length < 200; i++) {
    sec += Math.floor(Math.random() * 8) + 3;
    const doc = docs[i % docs.length];
    const pageNum = (i % doc.pages) + 1;
    const promptTokens = 1024 + Math.floor(Math.random() * 200);
    const compTokens = 180 + Math.floor(Math.random() * 250);
    const latency = (0.75 + Math.random() * 0.65).toFixed(2);

    if (i % 7 === 0) {
      logs.push(`[${formatTime(sec)}] [HEALTH] [ServerManager] Periodic probe: GET /health HTTP/1.1 -> 200 OK (latency: 4ms)`);
    } else if (i === 14) {
      logs.push(`[${formatTime(sec)}] [WARN] [Pipeline] Page ${pageNum} of arsip-kolonial-1892.png reached token ceiling (4096 tokens). Output marked truncated.`);
    } else {
      logs.push(
        `[${formatTime(sec)}] [OCR] POST /v1/chat/completions -> doc: ${doc.name} (p.${pageNum}/${doc.pages}) [200 OK] prompt_tokens: ${promptTokens}, completion_tokens: ${compTokens}, latency: ${latency}s`
      );
    }
  }

  return logs.slice(0, 200);
};

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
  isEngineRunning,
}) => {
  const [filterText, setFilterText] = useState('');
  const [levelFilter, setLevelFilter] = useState<'ALL' | 'INFO' | 'HEALTH' | 'OCR' | 'WARN' | 'ERROR'>('ALL');
  const [autoScroll, setAutoScroll] = useState(true);
  const [copied, setCopied] = useState(false);
  const [logs] = useState<string[]>(() => generateInitialLogs());
  const logContainerRef = useRef<HTMLDivElement>(null);

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
                  PID 14288
                </span>
                <span className={`text-[11px] font-mono font-medium px-2 py-0.5 rounded border ${
                  isEngineRunning 
                    ? 'bg-[#0F766E]/10 dark:bg-[var(--success)]/10 text-[#0F766E] dark:text-[var(--success)] border-[#0F766E]/30 dark:border-[var(--success)]/30' 
                    : 'bg-red-50 dark:bg-[var(--danger)]/10 text-red-700 dark:text-[var(--danger)] border-red-200 dark:border-[var(--danger)]/30'
                }`}>
                  {isEngineRunning ? '● RUNNING :8080' : '○ OFFLINE'}
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

        {/* Spike Slice Notice */}
        <div className="px-5 pt-3 shrink-0">
          <div className="mb-4 p-3 bg-amber-500/10 border border-amber-500/30 text-amber-600 dark:text-amber-400 rounded-lg text-xs font-mono">
            Spike Slice Notice: This panel is a visual preview from the mockup and is not connected to live settings/logs in this vertical slice. Deferred to Phase 2.
          </div>
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
            Showing {filteredLogs.length} of {logs.length} entries · Live stdout / stderr from ServerManager ·{' '}
            <code className="text-[#14213D] dark:text-[var(--text-1)] font-mono">%LOCALAPPDATA%\AksaraSight\logs\app.log</code>
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
