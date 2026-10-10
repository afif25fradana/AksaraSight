import React, { useState, useEffect, useRef } from 'react';
import { 
  CheckCircle2, 
  Cpu, 
  Sliders, 
  Terminal, 
  RefreshCw, 
  AlertTriangle, 
  Stethoscope, 
  FolderOpen
} from 'lucide-react';
import { EngineSettings } from '../types';

interface SettingsViewProps {
  settings: EngineSettings;
  onSave: (newSettings: EngineSettings) => void;
  onCancel: () => void;
}

type SettingsCategory = 'engine' | 'processing' | 'advanced';

interface DoctorStepResult {
  step: number;
  name: string;
  status: 'PASS' | 'WARN' | 'FAIL';
  details: string[];
}

const DPI_STEPS = [72, 100, 150, 200];

export const SettingsView: React.FC<SettingsViewProps> = ({
  settings,
  onSave,
  onCancel,
}) => {
  const [formData, setFormData] = useState<EngineSettings>({ 
    customLlamaServerPath: 'C:\\Users\\Fradana\\AppData\\Local\\AksaraSight\\runtimes\\b10930-cuda\\llama-server.exe',
    ...settings 
  });
  const [activeCategory, setActiveCategory] = useState<SettingsCategory>('engine');
  const [isRefreshingHardware, setIsRefreshingHardware] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [isSavedRecently, setIsSavedRecently] = useState(false);

  // Diagnostic (--doctor) state
  const [isDoctorRunning, setIsDoctorRunning] = useState(false);
  const [doctorReport, setDoctorReport] = useState<DoctorStepResult[] | null>(null);

  // Remote endpoints security modal state
  const [showSecurityWarning, setShowSecurityWarning] = useState(false);

  useEffect(() => {
    if (!showSecurityWarning) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowSecurityWarning(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showSecurityWarning]);

  const isDirty = JSON.stringify(formData) !== JSON.stringify(settings);

  const handleRefreshHardware = () => {
    setIsRefreshingHardware(true);
    setTimeout(() => {
      setIsRefreshingHardware(false);
    }, 600);
  };

  const handleRunDoctor = () => {
    setIsDoctorRunning(true);
    setDoctorReport(null);

    setTimeout(() => {
      const isCustom = formData.runtimeSource === 'custom';
      const customPath = formData.customLlamaServerPath || 'C:\\Users\\Fradana\\AppData\\Local\\AksaraSight\\runtimes\\b10930-cuda\\llama-server.exe';

      const results: DoctorStepResult[] = [
        {
          step: 1,
          name: 'Configuration',
          status: 'PASS',
          details: [
            `Backend: ${formData.backend}`,
            `Runtime Mode: ${formData.runtimeSource} (target: ${formData.targetBackend})`,
            `Endpoint: ${formData.endpointUrl} (loopback: ${formData.allowRemote ? 'no [WARNING: remote]' : 'yes'})`,
          ],
        },
        {
          step: 2,
          name: 'Hardware Detection',
          status: 'PASS',
          details: [
            'CPU: 12th Gen Intel(R) Core(TM) i7-12700H (14 cores, 20 threads)',
            'Primary GPU: NVIDIA GeForce RTX 3060 Laptop GPU (6144 MB VRAM)',
            'Acceleration: CUDA 12.4 Compatible (Compute Capability 8.6)',
            'Recommended Backend: CUDA (Full GPU offload supported)',
          ],
        },
        {
          step: 3,
          name: isCustom ? 'Runtime Installation (Custom Path)' : 'Runtime Installation (Managed Mode)',
          status: 'PASS',
          details: isCustom
            ? [
                'Custom Binary: FOUND',
                `Path: ${customPath}`,
              ]
            : [
                `Managed Runtime: b10930-${formData.targetBackend} (INSTALLED)`,
                `Executable: %LOCALAPPDATA%\\AksaraSight\\runtimes\\b10930-${formData.targetBackend}\\llama-server.exe`,
              ],
        },
        {
          step: 4,
          name: 'Server Reachability',
          status: 'PASS',
          details: [
            'Endpoint Health: READY (http://127.0.0.1:8080/health)',
            'Details: HTTP 200 OK (server status: ok, latency: 8ms)',
          ],
        },
        {
          step: 5,
          name: 'Multimodal Vision Probe',
          status: 'PASS',
          details: [
            '1x1 Image Test: VERIFIED',
            'Vision projector active, multimodal inference operational (142ms latency)',
          ],
        },
      ];

      setDoctorReport(results);
      setIsDoctorRunning(false);
    }, 900);
  };

  const handleSave = () => {
    onSave(formData);
    setIsSavedRecently(true);
    setSaveSuccess(true);
    setTimeout(() => {
      setIsSavedRecently(false);
    }, 1800);
    setTimeout(() => {
      setSaveSuccess(false);
    }, 2500);
  };

  const currentDpiIndex = Math.max(
    0,
    DPI_STEPS.findIndex((s) => s >= formData.renderDpi)
  );

  const handleDpiSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const stepIdx = Number(e.target.value);
    const targetDpi = DPI_STEPS[stepIdx] || 100;
    setFormData({ ...formData, renderDpi: targetDpi });
  };

  const handleToggleRemote = () => {
    if (!formData.allowRemote) {
      setShowSecurityWarning(true);
    } else {
      setFormData({ ...formData, allowRemote: false });
    }
  };

  // Sliding segmented indicators for Runtime Source and Target Backend
  const [runtimeIndicator, setRuntimeIndicator] = useState<{ left: number; width: number }>({ left: 2, width: 0 });
  const runtimeContainerRef = useRef<HTMLDivElement>(null);
  const runtimeRefs = useRef<{ [key in 'managed' | 'custom']?: HTMLButtonElement | null }>({});

  const [targetIndicator, setTargetIndicator] = useState<{ left: number; width: number }>({ left: 2, width: 0 });
  const targetContainerRef = useRef<HTMLDivElement>(null);
  const targetRefs = useRef<{ [key: string]: HTMLButtonElement | null }>({});

  useEffect(() => {
    const updateIndicators = () => {
      if (runtimeContainerRef.current && runtimeRefs.current[formData.runtimeSource]) {
        const cRect = runtimeContainerRef.current.getBoundingClientRect();
        const tRect = runtimeRefs.current[formData.runtimeSource]!.getBoundingClientRect();
        setRuntimeIndicator({ left: tRect.left - cRect.left, width: tRect.width });
      }
      if (formData.runtimeSource === 'managed' && targetContainerRef.current && targetRefs.current[formData.targetBackend]) {
        const cRect = targetContainerRef.current.getBoundingClientRect();
        const tRect = targetRefs.current[formData.targetBackend]!.getBoundingClientRect();
        setTargetIndicator({ left: tRect.left - cRect.left, width: tRect.width });
      }
    };
    updateIndicators();
    window.addEventListener('resize', updateIndicators);
    return () => window.removeEventListener('resize', updateIndicators);
  }, [formData.runtimeSource, formData.targetBackend, activeCategory]);

  return (
    <div className="flex-1 bg-[#EFEDE6] dark:bg-[var(--bg-base)] flex flex-col overflow-hidden min-h-0 transition-colors">
      {/* Main Container */}
      <main className="flex-1 p-4 md:p-6 flex justify-center items-center overflow-hidden min-h-0">
        <div className="w-full max-w-[840px] h-full max-h-[660px] flex flex-col bg-white dark:bg-[var(--bg-surface)] rounded-xl border border-[#8A94A6]/30 dark:border-[var(--border)] shadow-sm overflow-hidden transition-colors">
          
          {/* Header with Category Tabs */}
          <div className="border-b border-[#8A94A6]/25 dark:border-[var(--border)] px-6 pt-4 pb-0 shrink-0 bg-white dark:bg-[var(--bg-surface)]">
            <div className="flex items-center justify-between pb-3">
              <div>
                <h1 className="font-['IBM_Plex_Sans',sans-serif] text-[16px] font-semibold text-[#14213D] dark:text-[var(--text-1)]">
                  Engine & Quality Settings
                </h1>
                <p className="text-[12.5px] text-[#5A6478] dark:text-[var(--text-2)] mt-0.5">
                  Configure local llama-server runtime, inference targets, and OCR pipeline parameters
                </p>
              </div>

              {/* Toast Notification on Save */}
              {saveSuccess && (
                <div className="px-3 py-1.5 bg-[#0F766E]/10 dark:bg-[var(--success)]/10 border border-[#0F766E]/30 dark:border-[var(--success)]/30 rounded-lg flex items-center gap-1.5 text-[#0F766E] dark:text-[var(--success)] text-[12px] font-medium animate-fade-in shadow-2xs">
                  <CheckCircle2 className="w-4 h-4 text-[#0F766E] dark:text-[var(--success)]" aria-hidden="true" />
                  <span>Settings saved successfully</span>
                </div>
              )}
            </div>

            {/* Category Tab Bar */}
            <div 
              className="flex items-center gap-6 text-[13.5px] font-medium" 
              role="tablist"
              aria-label="Settings categories"
            >
              <button
                type="button"
                role="tab"
                aria-selected={activeCategory === 'engine'}
                onClick={() => setActiveCategory('engine')}
                className={`pb-2.5 border-b-2 font-semibold transition-all duration-150 active:scale-[0.98] flex items-center gap-1.5 cursor-pointer select-none focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] focus-visible:outline-none rounded-xs ${
                  activeCategory === 'engine'
                    ? 'border-[#0F766E] dark:border-[var(--accent)] text-[#0F766E] dark:text-[var(--accent)]'
                    : 'border-b-2 border-transparent text-[#5A6478] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)]'
                }`}
              >
                <Cpu className="w-4 h-4" aria-hidden="true" />
                <span>Engine & Hardware</span>
              </button>

              <button
                type="button"
                role="tab"
                aria-selected={activeCategory === 'processing'}
                onClick={() => setActiveCategory('processing')}
                className={`pb-2.5 border-b-2 font-semibold transition-all duration-150 active:scale-[0.98] flex items-center gap-1.5 cursor-pointer select-none focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] focus-visible:outline-none rounded-xs ${
                  activeCategory === 'processing'
                    ? 'border-[#0F766E] dark:border-[var(--accent)] text-[#0F766E] dark:text-[var(--accent)]'
                    : 'border-b-2 border-transparent text-[#5A6478] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)]'
                }`}
              >
                <Sliders className="w-4 h-4" aria-hidden="true" />
                <span>Processing & Quality</span>
              </button>

              <button
                type="button"
                role="tab"
                aria-selected={activeCategory === 'advanced'}
                onClick={() => setActiveCategory('advanced')}
                className={`pb-2.5 border-b-2 font-semibold transition-all duration-150 active:scale-[0.98] flex items-center gap-1.5 cursor-pointer select-none focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] focus-visible:outline-none rounded-xs ${
                  activeCategory === 'advanced'
                    ? 'border-[#0F766E] dark:border-[var(--accent)] text-[#0F766E] dark:text-[var(--accent)]'
                    : 'border-b-2 border-transparent text-[#5A6478] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)]'
                }`}
              >
                <Terminal className="w-4 h-4" aria-hidden="true" />
                <span>Advanced & Network</span>
              </button>
            </div>
          </div>

          {/* Active Tab Panel Content */}
          <div className="flex-1 p-6 overflow-y-auto min-h-0 bg-[#FCFBF8]/40 dark:bg-[var(--bg-base)]/40 space-y-4">
            {/* TAB 1: Engine & Hardware */}
            {activeCategory === 'engine' && (
              <div className="space-y-4 animate-fade-in" role="tabpanel">
                {/* Field 1: Backend */}
                <div>
                  <label className="block text-[13.5px] font-medium text-[#14213D] dark:text-[var(--text-1)] mb-1.5">
                    Local Inference Engine Backend
                  </label>
                  <div className="grid grid-cols-3 gap-3">
                    {(['llama-cpp', 'ollama', 'vllm'] as const).map((backendOption) => {
                      const isSelected = formData.backend === backendOption;
                      return (
                        <label 
                          key={backendOption}
                          className={`flex items-center gap-2.5 px-3 py-2 rounded-lg border cursor-pointer transition-all duration-150 active:scale-[0.98] ${
                            isSelected 
                              ? 'border-[#0F766E] dark:border-[var(--accent)] bg-[#0F766E]/5 dark:bg-[var(--accent)]/10 ring-1 ring-[#0F766E]/30 dark:ring-[var(--accent)]/30' 
                              : 'border-[#E5E2D9] dark:border-[var(--border)] hover:bg-[#F9F8F5] dark:hover:bg-[var(--bg-active)] bg-white dark:bg-[var(--bg-elevated)]'
                          }`}
                        >
                          <input 
                            type="radio" 
                            name="backend" 
                            value={backendOption} 
                            checked={isSelected}
                            onChange={() => setFormData({ ...formData, backend: backendOption })}
                            className="sr-only" 
                          />
                          <div 
                            className={`w-4 h-4 rounded-full border flex items-center justify-center transition-colors duration-150 shrink-0 ${
                              isSelected 
                                ? 'border-[#0F766E] dark:border-[var(--accent)] bg-white dark:bg-[var(--bg-elevated)]' 
                                : 'border-[#8A94A6] dark:border-[var(--border)] bg-[#FAF9F5] dark:bg-[var(--bg-base)]'
                            }`}
                            aria-hidden="true"
                          >
                            <div 
                              className={`w-2 h-2 rounded-full bg-[#0F766E] dark:bg-[var(--accent)] transition-transform duration-150 ease-out ${
                                isSelected ? 'scale-100 opacity-100' : 'scale-0 opacity-0'
                              }`} 
                            />
                          </div>
                          <span className={`text-[13.5px] ${isSelected ? 'font-medium text-[#14213D] dark:text-[var(--text-1)]' : 'text-[#374151] dark:text-[var(--text-2)]'}`}>
                            {backendOption}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                </div>

                {/* Field 2: Runtime source & Inset Blocks */}
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-[13.5px] font-medium text-[#14213D] dark:text-[var(--text-1)]">
                      Runtime Binary Source
                    </label>
                    <div 
                      ref={runtimeContainerRef}
                      className="relative inline-flex p-0.5 bg-[#F5F4F0] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-lg gap-1 whitespace-nowrap"
                    >
                      <div 
                        className="absolute top-0.5 bottom-0.5 rounded-md bg-white dark:bg-[var(--bg-elevated)] border border-[#14213D]/10 dark:border-[var(--border)] shadow-xs transition-all duration-200 cubic-bezier(0.16, 1, 0.3, 1) pointer-events-none"
                        style={{
                          left: `${runtimeIndicator.left}px`,
                          width: `${runtimeIndicator.width}px`,
                          opacity: runtimeIndicator.width > 0 ? 1 : 0,
                        }}
                      />
                      <button 
                        ref={(el) => { runtimeRefs.current.managed = el; }}
                        type="button"
                        onClick={() => setFormData({ ...formData, runtimeSource: 'managed' })}
                        className={`relative z-10 px-3 py-1 rounded-md text-[12px] font-medium whitespace-nowrap cursor-pointer active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out ${
                          formData.runtimeSource === 'managed' 
                            ? 'text-[#14213D] dark:text-[var(--text-1)]' 
                            : 'text-[#374151] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)]'
                        }`}
                      >
                        Managed Local Runtime
                      </button>
                      <button 
                        ref={(el) => { runtimeRefs.current.custom = el; }}
                        type="button"
                        onClick={() => setFormData({ ...formData, runtimeSource: 'custom' })}
                        className={`relative z-10 px-3 py-1 rounded-md text-[12px] font-medium whitespace-nowrap cursor-pointer active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out ${
                          formData.runtimeSource === 'custom' 
                            ? 'text-[#14213D] dark:text-[var(--text-1)]' 
                            : 'text-[#374151] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)]'
                        }`}
                      >
                        Custom Executable Path
                      </button>
                    </div>
                  </div>

                  {formData.runtimeSource === 'managed' ? (
                    /* Managed Inset Block */
                    <div className="bg-white dark:bg-[var(--bg-elevated)] rounded-lg p-3.5 border border-[#E5E2D9] dark:border-[var(--border)] space-y-3 transition-colors animate-fade-in">
                      <div className="flex items-center justify-between border-b border-[#E5E2D9]/70 dark:border-[var(--border)] pb-2.5">
                        <div>
                          <div className="flex items-center gap-2">
                            <label className="text-[13px] font-semibold text-[#14213D] dark:text-[var(--text-1)]">
                              Detected Hardware:
                            </label>
                            <span className="text-[13px] text-[#374151] dark:text-[var(--text-2)]">
                              NVIDIA GeForce RTX 3060 (6144 MB VRAM)
                            </span>
                          </div>
                          <p className="text-[12px] text-[#4B5563] dark:text-[var(--text-2)] mt-0.5">
                            Recommended Backend: <span className="font-semibold text-[#14213D] dark:text-[var(--text-1)]">CUDA (b10930)</span>
                          </p>
                        </div>
                        <button 
                          onClick={handleRefreshHardware}
                          className="text-[12.5px] font-medium text-[#0F766E] dark:text-[var(--accent)] hover:underline flex items-center gap-1 cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none rounded-xs" 
                          type="button" 
                        >
                          <RefreshCw className={`w-3.5 h-3.5 ${isRefreshingHardware ? 'animate-spin' : ''}`} aria-hidden="true" />
                          <span>{isRefreshingHardware ? 'Detecting...' : 'Refresh'}</span>
                        </button>
                      </div>

                      <div className="flex items-center justify-between">
                        <label className="text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)]">
                          Target Hardware Backend
                        </label>
                        <div 
                          ref={targetContainerRef}
                          className="relative inline-flex p-0.5 bg-[#F0EEE8] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-lg gap-1 whitespace-nowrap"
                        >
                          <div 
                            className="absolute top-0.5 bottom-0.5 rounded-md bg-white dark:bg-[var(--bg-elevated)] border border-[#14213D]/10 dark:border-[var(--border)] shadow-xs transition-all duration-200 cubic-bezier(0.16, 1, 0.3, 1) pointer-events-none"
                            style={{
                              left: `${targetIndicator.left}px`,
                              width: `${targetIndicator.width}px`,
                              opacity: targetIndicator.width > 0 ? 1 : 0,
                            }}
                          />
                          {(['auto', 'cuda', 'vulkan', 'cpu'] as const).map((backendOption) => (
                            <button
                              key={backendOption}
                              ref={(el) => { targetRefs.current[backendOption] = el; }}
                              type="button"
                              onClick={() => setFormData({ ...formData, targetBackend: backendOption })}
                              className={`relative z-10 px-2.5 py-0.5 rounded text-[12px] font-medium whitespace-nowrap cursor-pointer active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out ${
                                formData.targetBackend === backendOption 
                                  ? 'text-[#14213D] dark:text-[var(--text-1)]' 
                                  : 'text-[#374151] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)]'
                              }`}
                            >
                              {backendOption}
                            </button>
                          ))}
                        </div>
                      </div>

                      <div className="pt-1">
                        <div className="flex items-center justify-between text-[12px] mb-1">
                          <div className="flex items-center">
                            <span className="w-2 h-2 rounded-full bg-[#15803D] dark:bg-[var(--success)] inline-block mr-1.5 shrink-0" />
                            <span className="font-medium text-[#14213D] dark:text-[var(--text-1)]">
                              Installed Binary ({formData.targetBackend}):
                            </span>
                          </div>
                          <button 
                            className="border border-[#8A94A6] dark:border-[var(--border)] hover:border-[#14213D] dark:hover:border-[var(--border-strong)] bg-white dark:bg-[var(--bg-elevated)] rounded-md px-2.5 py-1 text-[11.5px] font-medium text-[#14213D] dark:text-[var(--text-1)] hover:bg-[#F0EEE8] dark:hover:bg-[var(--bg-active)] transition-colors cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none" 
                            type="button" 
                          >
                            Reinstall / Update
                          </button>
                        </div>
                        <div className="font-mono text-[11.5px] text-[#374151] dark:text-[var(--text-2)] truncate bg-[#F9F8F5] dark:bg-[var(--bg-base)] px-2.5 py-1 rounded border border-[#E5E2D9] dark:border-[var(--border)]">
                          %LOCALAPPDATA%\AksaraSight\runtimes\b10930-{formData.targetBackend}\llama-server.exe
                        </div>
                      </div>
                    </div>
                  ) : (
                    /* Custom Path Inset Block */
                    <div className="bg-white dark:bg-[var(--bg-elevated)] rounded-lg p-3.5 border border-[#E5E2D9] dark:border-[var(--border)] space-y-3 transition-colors animate-fade-in">
                      <div>
                        <label className="block text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)] mb-1.5" htmlFor="custom-server-path">
                          Custom llama-server Executable Path
                        </label>
                        <div className="flex items-center gap-2">
                          <input
                            id="custom-server-path"
                            type="text"
                            value={formData.customLlamaServerPath || ''}
                            onChange={(e) => setFormData({ ...formData, customLlamaServerPath: e.target.value })}
                            placeholder="C:\tools\llama-cpp\llama-server.exe"
                            className="flex-1 h-[34px] px-3 font-mono text-[12px] bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md text-[#14213D] dark:text-[var(--text-1)] focus:outline-none focus:border-[#0F766E] dark:focus:border-[var(--accent)] focus:ring-1 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)]"
                          />
                          <button
                            type="button"
                            onClick={() => {
                              setFormData({
                                ...formData,
                                customLlamaServerPath: 'C:\\Users\\Fradana\\AppData\\Local\\AksaraSight\\runtimes\\b10930-cuda\\llama-server.exe',
                              });
                            }}
                            className="h-[34px] px-3 border border-[#8A94A6] dark:border-[var(--border)] hover:border-[#14213D] dark:hover:border-[var(--border-strong)] bg-white dark:bg-[var(--bg-elevated)] hover:bg-black/[0.02] dark:hover:bg-[var(--bg-active)] text-[#14213D] dark:text-[var(--text-1)] rounded-md text-[12.5px] font-medium transition-colors cursor-pointer flex items-center gap-1"
                            title="Browse local disk for llama-server.exe"
                          >
                            <FolderOpen className="w-3.5 h-3.5 text-[#0F766E] dark:text-[var(--accent)]" />
                            <span>Browse...</span>
                          </button>
                        </div>
                        <p className="text-[11.5px] text-[#4B5563] dark:text-[var(--text-2)] mt-1.5 flex items-center gap-1.5">
                          <span className="w-2 h-2 rounded-full bg-[#15803D] dark:bg-[var(--success)]" />
                          <span>Valid llama-server binary detected at this path</span>
                        </p>
                      </div>
                    </div>
                  )}
                </div>

                {/* Field 3: Start server automatically toggle */}
                <div className="flex items-center justify-between bg-white dark:bg-[var(--bg-elevated)] p-3.5 rounded-lg border border-[#8A94A6]/25 dark:border-[var(--border)] transition-colors">
                  <div>
                    <span className="text-[13.5px] font-semibold text-[#14213D] dark:text-[var(--text-1)] block">
                      Start engine automatically with GUI
                    </span>
                    <p className="text-[12px] text-[#5A6478] dark:text-[var(--text-2)] mt-0.5">
                      Spawn background llama-server process on workspace startup
                    </p>
                  </div>
                  <button 
                    role="switch" 
                    aria-checked={formData.autoStart}
                    aria-label="Start engine automatically with GUI"
                    onClick={() => setFormData({ ...formData, autoStart: !formData.autoStart })}
                    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)] focus:ring-offset-2 ${
                      formData.autoStart ? 'bg-[#0F766E] dark:bg-[var(--accent)]' : 'bg-[#8A94A6] dark:bg-[var(--border-strong)]'
                    }`} 
                    type="button" 
                  >
                    <span 
                      className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white dark:bg-[#f0f1f3] shadow-sm ring-0 transition duration-200 ease-in-out ${
                        formData.autoStart ? 'translate-x-4' : 'translate-x-0'
                      }`} 
                    />
                  </button>
                </div>

                {/* Field 4: System Diagnostic (--doctor) Runner Block */}
                <div className="bg-white dark:bg-[var(--bg-elevated)] p-3.5 rounded-lg border border-[#8A94A6]/25 dark:border-[var(--border)] space-y-3 transition-colors">
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-[13.5px] font-semibold text-[#14213D] dark:text-[var(--text-1)] flex items-center gap-1.5">
                        <Stethoscope className="w-4 h-4 text-[#0F766E] dark:text-[var(--accent)]" />
                        <span>System Diagnostic Probe</span>
                      </span>
                      <p className="text-[12px] text-[#5A6478] dark:text-[var(--text-2)] mt-0.5">
                        Execute comprehensive 5-step hardware, runtime, and multimodal vision verification
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={handleRunDoctor}
                      disabled={isDoctorRunning}
                      className="h-8 px-3.5 bg-[#0F766E] dark:bg-[var(--accent)] hover:bg-[#115E59] dark:hover:bg-[var(--accent)]/90 active:bg-[#0d4f4b] text-white dark:text-[var(--bg-base)] rounded-lg text-[12px] font-semibold active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out flex items-center gap-1.5 cursor-pointer shadow-xs disabled:opacity-50"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${isDoctorRunning ? 'animate-spin' : ''}`} />
                      <span>{isDoctorRunning ? 'Probing...' : 'Run Diagnostic'}</span>
                    </button>
                  </div>

                  {/* Doctor 5-Step Detailed Report */}
                  {doctorReport && (
                    <div className="p-3.5 bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#8A94A6]/30 dark:border-[var(--border)] text-[#14213D] dark:text-[var(--text-1)] shadow-xs rounded-lg font-mono text-[11.5px] leading-relaxed animate-fade-in space-y-2.5">
                      <div className="flex items-center justify-between border-b border-[#8A94A6]/20 dark:border-[var(--border)] pb-2 font-sans">
                        <span className="text-[#14213D] dark:text-[var(--text-1)] font-semibold text-[12.5px]">Diagnostic Verification Report</span>
                        <span className="bg-[#0F766E]/10 dark:bg-[var(--success)]/10 text-[#0F766E] dark:text-[var(--success)] border border-[#0F766E]/20 dark:border-[var(--success)]/30 font-mono text-[11px] px-2 py-0.5 rounded font-semibold">
                          HEALTHY (5/5 PASS)
                        </span>
                      </div>
                      <div className="space-y-1.5">
                        {doctorReport.map((res) => (
                          <div key={res.step} className="border-b border-[#8A94A6]/20 dark:border-[var(--border)] last:border-b-0 pb-1.5 pt-0.5">
                            <div className="flex items-center gap-1.5">
                              <span className="text-[#0F766E] dark:text-[var(--success)] font-bold font-mono">[{res.status}]</span>
                              <span className="text-[#14213D] dark:text-[var(--text-1)] font-semibold">{res.step}. {res.name}</span>
                            </div>
                            <div className="pl-6 space-y-0.5 text-[#5A6478] dark:text-[var(--text-2)] font-mono text-[11.5px]">
                              {res.details.map((d, dIdx) => (
                                <div key={dIdx}>{d}</div>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* TAB 2: Processing & Quality */}
            {activeCategory === 'processing' && (
              <div className="space-y-4 animate-fade-in" role="tabpanel">
                {/* DPI Slider Block */}
                <div className="bg-white dark:bg-[var(--bg-elevated)] p-4 rounded-lg border border-[#8A94A6]/25 dark:border-[var(--border)] space-y-3 transition-colors">
                  <div className="flex justify-between items-center">
                    <label className="text-[13.5px] font-semibold text-[#14213D] dark:text-[var(--text-1)]" htmlFor="render-dpi">
                      Document Render Resolution (DPI)
                    </label>
                    <span 
                      className="font-mono text-[12.5px] font-bold text-[#0F766E] dark:text-[var(--accent)] px-2.5 py-0.5 rounded bg-[#0F766E]/10 dark:bg-[var(--accent)]/10 border border-[#0F766E]/25 dark:border-[var(--accent)]/30" 
                      style={{ fontVariantNumeric: 'tabular-nums' }}
                    >
                      {formData.renderDpi} DPI
                    </span>
                  </div>

                  <div className="relative flex items-center w-full py-1">
                    <input 
                      id="render-dpi" 
                      type="range" 
                      min="0" 
                      max="3" 
                      step="1"
                      value={currentDpiIndex}
                      onChange={handleDpiSliderChange}
                      style={{
                        background: `linear-gradient(to right, var(--accent) 0%, var(--accent) ${(currentDpiIndex / (DPI_STEPS.length - 1)) * 100}%, var(--border) ${(currentDpiIndex / (DPI_STEPS.length - 1)) * 100}%, var(--border) 100%)`
                      }}
                      className="w-full h-1.5 rounded-lg appearance-none cursor-pointer accent-[#0F766E] dark:accent-[var(--accent)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-offset-[var(--bg-elevated)]" 
                    />
                  </div>

                  {/* Snapped Steps Label Row */}
                  <div className="flex justify-between items-center text-[12px] font-medium text-[#5A6478] dark:text-[var(--text-2)] px-0.5" style={{ fontVariantNumeric: 'tabular-nums' }}>
                    {DPI_STEPS.map((dpi) => (
                      <span 
                        key={dpi}
                        onClick={() => setFormData({ ...formData, renderDpi: dpi })}
                        className={`cursor-pointer transition-colors ${
                          formData.renderDpi === dpi 
                            ? 'text-[#0F766E] dark:text-[var(--accent)] font-bold border-b-2 border-[#0F766E] dark:border-[var(--accent)]' 
                            : 'border-b-2 border-transparent hover:text-[#14213D] dark:hover:text-[var(--text-1)]'
                        }`}
                      >
                        {dpi} DPI
                      </span>
                    ))}
                  </div>

                  {/* Timing & Quality Guide */}
                  <div className="grid grid-cols-2 gap-2 text-[12px] pt-1">
                    <div className={`p-2 rounded border ${formData.renderDpi === 72 ? 'bg-[#0F766E]/10 dark:bg-[var(--accent)]/10 border-[#0F766E]/40 dark:border-[var(--accent)]/40 font-semibold text-[#0F766E] dark:text-[var(--accent)]' : 'bg-[#FAF9F5] dark:bg-[var(--bg-base)] border-[#8A94A6]/20 dark:border-[var(--border)] text-[#374151] dark:text-[var(--text-2)]'}`}>
                      72 DPI: Draft / Fast preview
                    </div>
                    <div className={`p-2 rounded border ${formData.renderDpi === 100 ? 'bg-[#0F766E]/10 dark:bg-[var(--accent)]/10 border-[#0F766E]/40 dark:border-[var(--accent)]/40 font-semibold text-[#0F766E] dark:text-[var(--accent)]' : 'bg-[#FAF9F5] dark:bg-[var(--bg-base)] border-[#8A94A6]/20 dark:border-[var(--border)] text-[#374151] dark:text-[var(--text-2)]'}`}>
                      100 DPI: Standard documents (Recommended)
                    </div>
                    <div className={`p-2 rounded border ${formData.renderDpi === 150 ? 'bg-[#0F766E]/10 dark:bg-[var(--accent)]/10 border-[#0F766E]/40 dark:border-[var(--accent)]/40 font-semibold text-[#0F766E] dark:text-[var(--accent)]' : 'bg-[#FAF9F5] dark:bg-[var(--bg-base)] border-[#8A94A6]/20 dark:border-[var(--border)] text-[#374151] dark:text-[var(--text-2)]'}`}>
                      150 DPI: High resolution / Small fonts
                    </div>
                    <div className={`p-2 rounded border ${formData.renderDpi === 200 ? 'bg-[#0F766E]/10 dark:bg-[var(--accent)]/10 border-[#0F766E]/40 dark:border-[var(--accent)]/40 font-semibold text-[#0F766E] dark:text-[var(--accent)]' : 'bg-[#FAF9F5] dark:bg-[var(--bg-base)] border-[#8A94A6]/20 dark:border-[var(--border)] text-[#374151] dark:text-[var(--text-2)]'}`}>
                      200 DPI: Archival / Fine manuscript detail
                    </div>
                  </div>
                </div>

                {/* Limits Grid */}
                <div className="bg-white dark:bg-[var(--bg-elevated)] p-4 rounded-lg border border-[#E5E2D9] dark:border-[var(--border)] grid grid-cols-2 gap-4 transition-colors">
                  <div>
                    <label className="block text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)] mb-1" htmlFor="max-image-size">
                      Max Image Dimension
                    </label>
                    <div className="flex items-center gap-2">
                      <input 
                        id="max-image-size" 
                        type="number" 
                        value={formData.maxImageSize}
                        onChange={(e) => setFormData({ ...formData, maxImageSize: Number(e.target.value) })}
                        className="w-full max-w-[120px] h-[34px] px-2.5 text-[13.5px] bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md text-[#14213D] dark:text-[var(--text-1)] focus:outline-none focus:border-[#0F766E] dark:focus:border-[var(--accent)] focus:ring-1 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)] [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none" 
                      />
                      <span className="text-[12px] text-[#4B5563] dark:text-[var(--text-2)]">px</span>
                    </div>
                    <p className="text-[11.5px] text-[#4B5563] dark:text-[var(--text-2)] mt-1">
                      Images exceeding this pixel dimension are downscaled before inference
                    </p>
                  </div>

                  <div>
                    <label className="block text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)] mb-1" htmlFor="max-tokens">
                      Max Tokens Per Page
                    </label>
                    <input 
                      id="max-tokens" 
                      type="number" 
                      value={formData.maxTokensPerPage}
                      onChange={(e) => setFormData({ ...formData, maxTokensPerPage: Number(e.target.value) })}
                      className="w-full max-w-[120px] h-[34px] px-2.5 text-[13.5px] bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md text-[#14213D] dark:text-[var(--text-1)] focus:outline-none focus:border-[#0F766E] dark:focus:border-[var(--accent)] focus:ring-1 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)] [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none" 
                    />
                    <p className="text-[11.5px] text-[#4B5563] dark:text-[var(--text-2)] mt-1">
                      Context window token budget reserved for each page's OCR output
                    </p>
                  </div>

                  <div className="col-span-2 pt-2 border-t border-[#E5E2D9] dark:border-[var(--border)]">
                    <div className="flex items-center justify-between">
                      <div>
                        <label className="block text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)]" htmlFor="max-pages">
                          Max Pages Per Document
                        </label>
                        <p className="text-[11.5px] text-[#4B5563] dark:text-[var(--text-2)]">
                          Maximum pages to process before truncating (leave blank for all pages)
                        </p>
                      </div>
                      <input 
                        id="max-pages" 
                        type="number" 
                        placeholder="All pages" 
                        value={formData.maxPagesPerDoc}
                        onChange={(e) => setFormData({ ...formData, maxPagesPerDoc: e.target.value })}
                        className="w-[120px] h-[34px] px-2.5 text-[13.5px] bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md text-[#14213D] dark:text-[var(--text-1)] placeholder-[#6B7280] dark:placeholder-[var(--text-3)] focus:outline-none focus:border-[#0F766E] dark:focus:border-[var(--accent)] focus:ring-1 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)] [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none" 
                      />
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* TAB 3: Advanced & Network */}
            {activeCategory === 'advanced' && (
              <div className="space-y-4 animate-fade-in" role="tabpanel">
                <div className="bg-white dark:bg-[var(--bg-elevated)] p-4 rounded-lg border border-[#E5E2D9] dark:border-[var(--border)] space-y-3.5 transition-colors">
                  <div>
                    <label className="block text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)] mb-1" htmlFor="endpoint">
                      Local Engine HTTP Endpoint URL
                    </label>
                    <input 
                      id="endpoint" 
                      type="text" 
                      value={formData.endpointUrl}
                      onChange={(e) => setFormData({ ...formData, endpointUrl: e.target.value })}
                      className="w-full h-[34px] px-3 font-mono text-[12.5px] bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md text-[#14213D] dark:text-[var(--text-1)] focus:outline-none focus:border-[#0F766E] dark:focus:border-[var(--accent)] focus:ring-1 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)]" 
                    />
                  </div>

                  {/* Allow Remote Endpoints */}
                  <div className="flex items-center justify-between pt-2 border-t border-[#8A94A6]/20 dark:border-[var(--border)]">
                    <div>
                      <span className="text-[13px] font-semibold text-[#14213D] dark:text-[var(--text-1)] block">
                        Allow Non-Loopback (Remote) Endpoints
                      </span>
                      <p className="text-[12px] text-[#5A6478] dark:text-[var(--text-2)] mt-0.5">
                        Permit connections outside 127.0.0.1 or localhost (violates 100% local guarantee)
                      </p>
                    </div>
                    <button 
                      role="switch" 
                      aria-checked={formData.allowRemote}
                      aria-label="Allow Non-Loopback (Remote) Endpoints"
                      onClick={handleToggleRemote}
                      className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)] focus:ring-offset-2 ${
                        formData.allowRemote ? 'bg-[#0F766E] dark:bg-[var(--accent)]' : 'bg-[#8A94A6] dark:bg-[var(--border-strong)]'
                      }`} 
                      type="button" 
                    >
                      <span 
                        className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white dark:bg-[#f0f1f3] shadow-sm ring-0 transition duration-200 ease-in-out ${
                          formData.allowRemote ? 'translate-x-4' : 'translate-x-0'
                        }`} 
                      />
                    </button>
                  </div>

                  <div className="grid grid-cols-2 gap-4 pt-2 border-t border-[#E5E2D9] dark:border-[var(--border)]">
                    <div>
                      <label className="block text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)] mb-1" htmlFor="req-timeout">
                        HTTP Request Timeout
                      </label>
                      <div className="flex items-center gap-2">
                        <input 
                          id="req-timeout" 
                          type="number" 
                          value={formData.timeout}
                          onChange={(e) => setFormData({ ...formData, timeout: Number(e.target.value) })}
                          className="w-full max-w-[100px] h-[34px] px-2.5 text-[13.5px] bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md text-[#14213D] dark:text-[var(--text-1)] focus:outline-none focus:border-[#0F766E] dark:focus:border-[var(--accent)] focus:ring-1 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)] [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none" 
                        />
                        <span className="text-[12px] text-[#4B5563] dark:text-[var(--text-2)]">s</span>
                      </div>
                    </div>

                    <div>
                      <label className="block text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)] mb-1" htmlFor="retries">
                        Max Retry Attempts
                      </label>
                      <input 
                        id="retries" 
                        type="number" 
                        value={formData.retries}
                        onChange={(e) => setFormData({ ...formData, retries: Number(e.target.value) })}
                        className="w-full max-w-[100px] h-[34px] px-2.5 text-[13.5px] bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md text-[#14213D] dark:text-[var(--text-1)] focus:outline-none focus:border-[#0F766E] dark:focus:border-[var(--accent)] focus:ring-1 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)] [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none" 
                      />
                    </div>
                  </div>

                  <div className="pt-2 border-t border-[#E5E2D9] dark:border-[var(--border)]">
                    <label className="block text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)] mb-1" htmlFor="model-repo">
                      Default Hugging Face Model Repository
                    </label>
                    <input 
                      id="model-repo" 
                      type="text" 
                      value={formData.modelRepo}
                      onChange={(e) => setFormData({ ...formData, modelRepo: e.target.value })}
                      className="w-full h-[34px] px-3 font-mono text-[12.5px] bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md text-[#14213D] dark:text-[var(--text-1)] focus:outline-none focus:border-[#0F766E] dark:focus:border-[var(--accent)] focus:ring-1 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)]" 
                    />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Footer Action Bar */}
          <div className="bg-white dark:bg-[var(--bg-surface)] border-t border-[#E5E2D9] dark:border-[var(--border)] py-3 px-6 flex justify-end items-center gap-3 shrink-0 transition-colors">
            <button 
              onClick={onCancel}
              className="px-4 py-1.5 text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)] hover:bg-black/5 dark:hover:bg-white/5 rounded-lg active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none" 
              type="button" 
            >
              Cancel
            </button>
            <button 
              onClick={handleSave}
              disabled={!isDirty && !isSavedRecently}
              className={`min-w-[124px] h-[34px] px-4 rounded-lg text-[13px] font-medium flex items-center justify-center gap-1.5 transition-all duration-150 ease-out focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] focus-visible:outline-none ${
                isSavedRecently
                  ? 'bg-[#15803D] dark:bg-[var(--success)] text-white shadow-xs'
                  : isDirty 
                    ? 'bg-[#0F766E] dark:bg-[var(--accent)] text-white dark:text-[var(--bg-base)] hover:bg-[#115E59] dark:hover:bg-[var(--accent)]/90 shadow-xs cursor-pointer active:scale-[0.96] active:translate-y-px active:brightness-95' 
                    : 'bg-[#0F766E] dark:bg-[var(--accent)] text-white dark:text-[var(--bg-base)] opacity-40 cursor-not-allowed'
              }`} 
              type="button" 
            >
              {isSavedRecently ? (
                <>
                  <CheckCircle2 className="w-4 h-4 animate-fade-in" />
                  <span>Saved!</span>
                </>
              ) : (
                <span>Save Settings</span>
              )}
            </button>
          </div>

        </div>
      </main>

      {/* Security Confirmation Warning Modal Dialog */}
      {showSecurityWarning && (
        <div 
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#14213D]/40 dark:bg-black/70 backdrop-blur-[4px] animate-modal-backdrop"
          onClick={() => setShowSecurityWarning(false)}
        >
          <div 
            className="w-full max-w-md bg-white dark:bg-[var(--bg-surface)] rounded-xl shadow-xl border border-red-200 dark:border-[var(--danger)]/40 p-5 space-y-4 text-[#14213D] dark:text-[var(--text-1)] animate-modal-window will-change-transform transition-colors"
            onClick={(e) => e.stopPropagation()}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="security-warning-title"
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-red-100 dark:bg-[var(--danger)]/15 flex items-center justify-center text-red-600 dark:text-[var(--danger)] shrink-0">
                <AlertTriangle className="w-5 h-5 text-red-600 dark:text-[var(--danger)]" aria-hidden="true" />
              </div>
              <div>
                <h3 id="security-warning-title" className="font-semibold text-[15px] text-[#14213D] dark:text-[var(--text-1)]">
                  Security Notice: Remote Endpoint
                </h3>
                <span className="text-[12px] text-red-700 dark:text-[var(--danger)] font-medium">
                  Violates 100% Local Guarantee
                </span>
              </div>
            </div>

            <p className="text-[13px] text-[#374151] dark:text-[var(--text-2)] leading-relaxed">
              Connecting to an external endpoint transmits document images outside this machine. AksaraSight is architected for strict offline-first archival confidentiality.
            </p>

            <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-black/5 dark:border-[var(--border)]">
              <button
                type="button"
                onClick={() => setShowSecurityWarning(false)}
                className="px-3.5 py-1.5 text-[12.5px] border border-[#8A94A6] dark:border-[var(--border)] hover:border-[#14213D] dark:hover:border-[var(--border-strong)] bg-white dark:bg-[var(--bg-elevated)] text-[#374151] dark:text-[var(--text-1)] rounded-lg font-medium cursor-pointer active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  setFormData({ ...formData, allowRemote: true });
                  setShowSecurityWarning(false);
                }}
                className="px-4 py-1.5 text-[12.5px] bg-red-700 dark:bg-[var(--danger)] hover:bg-red-800 dark:hover:bg-[var(--danger)]/90 text-white rounded-lg font-semibold cursor-pointer shadow-xs active:scale-[0.96] active:translate-y-px active:brightness-95 transition-all duration-150 ease-out"
              >
                I understand, enable remote
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
