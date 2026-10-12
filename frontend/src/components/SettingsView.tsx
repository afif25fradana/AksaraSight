import React, { useState, useEffect, useMemo } from 'react';
import { 
  CheckCircle2, 
  Cpu, 
  Sliders, 
  Terminal, 
  RefreshCw, 
  AlertTriangle, 
  Stethoscope,
  Lock,
  ShieldCheck
} from 'lucide-react';
import { BackendSettings, DoctorReport, EngineSettings } from '../types';

interface SettingsViewProps {
  settings?: EngineSettings;
  onSave?: (newSettings: BackendSettings) => void;
  onCancel?: () => void;
}

type SettingsCategory = 'engine' | 'processing' | 'advanced';

const DPI_STEPS = [72, 100, 150, 200];

const DEFAULT_SETTINGS: BackendSettings = {
  backend: 'llama-cpp',
  local_endpoint: 'http://127.0.0.1:8080/v1',
  runtime_mode: 'managed',
  managed_backend_override: 'auto',
  dpi: 100,
  max_image_dimension: 2048,
  max_tokens: 4096,
  timeout: 60,
  max_retries: 2,
  auto_start_server: false,
  model_repo: 'ggml-org/GLM-OCR-GGUF',
  allow_remote: false,
  llama_server_path: null,
};

const MUTABLE_KEYS = [
  'dpi',
  'max_image_dimension',
  'max_tokens',
  'timeout',
  'max_retries',
  'auto_start_server',
] as const;

export const SettingsView: React.FC<SettingsViewProps> = ({
  settings,
  onSave,
  onCancel,
}) => {
  const [formData, setFormData] = useState<BackendSettings>(() => {
    return {
      ...DEFAULT_SETTINGS,
      ...(settings?.dpi !== undefined ? { dpi: settings.dpi } : {}),
      ...(settings?.renderDpi !== undefined ? { dpi: settings.renderDpi } : {}),
      ...(settings?.max_image_dimension !== undefined ? { max_image_dimension: settings.max_image_dimension } : {}),
      ...(settings?.maxImageSize !== undefined ? { max_image_dimension: settings.maxImageSize } : {}),
      ...(settings?.max_tokens !== undefined ? { max_tokens: settings.max_tokens } : {}),
      ...(settings?.maxTokensPerPage !== undefined ? { max_tokens: settings.maxTokensPerPage } : {}),
      ...(settings?.timeout !== undefined ? { timeout: settings.timeout } : {}),
      ...(settings?.max_retries !== undefined ? { max_retries: settings.max_retries } : {}),
      ...(settings?.retries !== undefined ? { max_retries: settings.retries } : {}),
      ...(settings?.auto_start_server !== undefined ? { auto_start_server: settings.auto_start_server } : {}),
      ...(settings?.autoStart !== undefined ? { auto_start_server: settings.autoStart } : {}),
      ...(settings?.backend ? { backend: settings.backend } : {}),
      ...(settings?.local_endpoint ? { local_endpoint: settings.local_endpoint } : {}),
      ...(settings?.endpointUrl ? { local_endpoint: settings.endpointUrl } : {}),
      ...(settings?.runtime_mode ? { runtime_mode: settings.runtime_mode } : {}),
      ...(settings?.runtimeSource ? { runtime_mode: settings.runtimeSource } : {}),
      ...(settings?.managed_backend_override !== undefined ? { managed_backend_override: settings.managed_backend_override } : {}),
      ...(settings?.targetBackend ? { managed_backend_override: settings.targetBackend } : {}),
      ...(settings?.model_repo ? { model_repo: settings.model_repo } : {}),
      ...(settings?.modelRepo ? { model_repo: settings.modelRepo } : {}),
      ...(settings?.llama_server_path ? { llama_server_path: settings.llama_server_path } : {}),
      ...(settings?.customLlamaServerPath ? { llama_server_path: settings.customLlamaServerPath } : {}),
    };
  });

  const [savedSettings, setSavedSettings] = useState<BackendSettings | null>(null);
  const [activeCategory, setActiveCategory] = useState<SettingsCategory>('engine');
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  // Diagnostic (--doctor) state
  const [isDoctorRunning, setIsDoctorRunning] = useState(false);
  const [isRefreshingHardware, setIsRefreshingHardware] = useState(false);
  const [doctorReport, setDoctorReport] = useState<DoctorReport | null>(null);
  const [doctorError, setDoctorError] = useState<string | null>(null);

  // Fetch real settings and latest cached doctor report on mount
  useEffect(() => {
    let isMounted = true;

    // 1. Fetch real settings from GET /api/settings
    fetch('/api/settings')
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: Partial<BackendSettings>) => {
        if (!isMounted) return;
        setFormData((prev) => {
          const merged: BackendSettings = {
            ...prev,
            ...data,
          };
          setSavedSettings(merged);
          return merged;
        });
      })
      .catch((err) => {
        console.warn('Could not fetch /api/settings on mount, using initial fallback:', err);
        if (isMounted) {
          setSavedSettings((prev) => prev || formData);
        }
      });

    // 2. Fetch cached doctor report from GET /api/doctor
    fetch('/api/doctor')
      .then(async (res) => {
        if (res.ok) {
          const data: DoctorReport = await res.json();
          if (isMounted && data && Array.isArray(data.checks)) {
            setDoctorReport(data);
          }
        }
      })
      .catch((err) => {
        console.warn('Could not fetch cached doctor report:', err);
      });

    return () => {
      isMounted = false;
    };
  }, []);

  // Compute dirty state: true only when mutable fields differ from savedSettings
  const isDirty = useMemo(() => {
    const baseline = savedSettings || formData;
    return MUTABLE_KEYS.some((key) => formData[key] !== baseline[key]);
  }, [formData, savedSettings]);

  // Run doctor diagnostics via POST /api/doctor
  const handleRunDoctor = async () => {
    setIsDoctorRunning(true);
    setDoctorError(null);
    try {
      const res = await fetch('/api/doctor', { method: 'POST' });
      if (res.ok) {
        const data: DoctorReport = await res.json();
        setDoctorReport(data);
      } else {
        const errData = await res.json().catch(() => ({ detail: 'Doctor run failed' }));
        setDoctorError(errData.detail || `Diagnostic failed with status ${res.status}`);
      }
    } catch (err: any) {
      setDoctorError(err.message || 'Network error running system diagnostic probe');
    } finally {
      setIsDoctorRunning(false);
      setIsRefreshingHardware(false);
    }
  };

  const handleRefreshHardware = () => {
    setIsRefreshingHardware(true);
    handleRunDoctor();
  };

  // Save settings via PATCH /api/settings with ONLY changed mutable fields
  const handleSave = async () => {
    const baseline = savedSettings || formData;
    const updates: Record<string, any> = {};

    for (const key of MUTABLE_KEYS) {
      if (formData[key] !== baseline[key]) {
        updates[key] = formData[key];
      }
    }

    if (Object.keys(updates).length === 0) return;

    setIsSaving(true);
    setSaveError(null);

    try {
      const res = await fetch('/api/settings', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });

      if (res.ok) {
        const data = await res.json();
        const updatedSettings: BackendSettings = data.settings || { ...baseline, ...updates };
        setSavedSettings(updatedSettings);
        setFormData(updatedSettings);
        setSaveSuccess(true);
        onSave?.(updatedSettings);
        setTimeout(() => setSaveSuccess(false), 2500);
      } else {
        const errData = await res.json().catch(() => ({ detail: 'Failed to update settings' }));
        setSaveError(errData.detail || `HTTP ${res.status}: Failed to update settings`);
        setSaveSuccess(false);
      }
    } catch (err: any) {
      setSaveError(err.message || 'Network error while updating settings');
      setSaveSuccess(false);
    } finally {
      setIsSaving(false);
    }
  };

  const currentDpiIndex = Math.max(
    0,
    DPI_STEPS.findIndex((s) => s >= formData.dpi)
  );

  const handleDpiSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const stepIdx = Number(e.target.value);
    const targetDpi = DPI_STEPS[stepIdx] || 100;
    setFormData((prev) => ({ ...prev, dpi: targetDpi }));
  };

  // Extract detected hardware from real doctor report if available
  const hardwareCheck = useMemo(() => {
    if (!doctorReport?.checks) return null;
    return doctorReport.checks.find(
      (c) =>
        c.category?.toLowerCase().includes('hardware') ||
        c.title?.toLowerCase().includes('hardware')
    );
  }, [doctorReport]);

  return (
    <div className="flex-1 bg-[#EFEDE6] dark:bg-[var(--bg-base)] flex flex-col overflow-hidden min-h-0 transition-colors">
      {/* Main Container */}
      <main className="flex-1 p-4 md:p-6 flex justify-center items-center overflow-hidden min-h-0">
        <div className="w-full max-w-[840px] h-full max-h-[660px] flex flex-col bg-white dark:bg-[var(--bg-surface)] rounded-xl border border-[#8A94A6]/30 dark:border-[var(--border)] shadow-sm overflow-hidden transition-colors">
          
          {/* Header with Category Tabs */}
          <div className="border-b border-[#8A94A6]/25 dark:border-[var(--border)] px-6 pt-4 pb-0 shrink-0 bg-white dark:bg-[var(--bg-surface)]">
            {/* Inline Error Banner if PATCH fails */}
            {saveError && (
              <div 
                role="alert" 
                className="mb-3 p-3 bg-red-50 dark:bg-[var(--danger)]/10 border border-red-200 dark:border-[var(--danger)]/30 text-red-700 dark:text-[var(--danger)] rounded-lg text-xs flex items-center justify-between"
              >
                <div className="flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 shrink-0" aria-hidden="true" />
                  <span>{saveError}</span>
                </div>
                <button 
                  type="button" 
                  onClick={() => setSaveError(null)} 
                  className="text-xs font-semibold underline ml-2 cursor-pointer"
                >
                  Dismiss
                </button>
              </div>
            )}

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
                <div 
                  role="status"
                  className="px-3 py-1.5 bg-[#0F766E]/10 dark:bg-[var(--success)]/10 border border-[#0F766E]/30 dark:border-[var(--success)]/30 rounded-lg flex items-center gap-1.5 text-[#0F766E] dark:text-[var(--success)] text-[12px] font-medium animate-fade-in shadow-2xs"
                >
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
                
                {/* Field 1: Backend (IMMUTABLE - READ ONLY) */}
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-[13.5px] font-medium text-[#14213D] dark:text-[var(--text-1)]">
                      Local Inference Engine Backend
                    </label>
                    <span className="inline-flex items-center gap-1 text-[11px] font-medium font-mono text-[#5A6478] dark:text-[var(--text-2)] bg-black/[0.04] dark:bg-[var(--bg-elevated)] px-2 py-0.5 rounded border border-black/5 dark:border-[var(--border)]">
                      <Lock className="w-3 h-3 text-[#5A6478] dark:text-[var(--text-2)]" aria-hidden="true" />
                      <span>Read-Only</span>
                    </span>
                  </div>
                  <div className="bg-[#FAF9F5] dark:bg-[var(--bg-base)] p-3 rounded-lg border border-[#E5E2D9] dark:border-[var(--border)] flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-semibold text-[13px] text-[#14213D] dark:text-[var(--text-1)]">
                        {formData.backend}
                      </span>
                      <span className="text-2xs text-[#0F766E] dark:text-[var(--accent)] font-medium bg-[#0F766E]/10 dark:bg-[var(--accent)]/15 px-1.5 py-0.5 rounded">
                        Active Backend
                      </span>
                    </div>
                    <span className="text-xs text-[#5A6478] dark:text-[var(--text-2)]">
                      Configured via environment / CLI flags
                    </span>
                  </div>
                </div>

                {/* Field 2: Runtime mode & Target Backend (IMMUTABLE - READ ONLY) */}
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-[13.5px] font-medium text-[#14213D] dark:text-[var(--text-1)]">
                      Runtime Binary Source & Mode
                    </label>
                    <span className="inline-flex items-center gap-1 text-[11px] font-medium font-mono text-[#5A6478] dark:text-[var(--text-2)] bg-black/[0.04] dark:bg-[var(--bg-elevated)] px-2 py-0.5 rounded border border-black/5 dark:border-[var(--border)]">
                      <Lock className="w-3 h-3 text-[#5A6478] dark:text-[var(--text-2)]" aria-hidden="true" />
                      <span>Read-Only</span>
                    </span>
                  </div>

                  <div className="bg-white dark:bg-[var(--bg-elevated)] rounded-lg p-3.5 border border-[#E5E2D9] dark:border-[var(--border)] space-y-3 transition-colors">
                    <div className="flex items-center justify-between border-b border-[#E5E2D9]/70 dark:border-[var(--border)] pb-2.5">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-[13px] font-semibold text-[#14213D] dark:text-[var(--text-1)]">
                            Runtime Mode:
                          </span>
                          <span className="font-mono text-[12.5px] text-[#374151] dark:text-[var(--text-2)] uppercase">
                            {formData.runtime_mode}
                          </span>
                        </div>
                        <p className="text-[12px] text-[#4B5563] dark:text-[var(--text-2)] mt-0.5">
                          Target Backend Override: <span className="font-semibold text-[#14213D] dark:text-[var(--text-1)] font-mono">{formData.managed_backend_override || 'auto'}</span>
                        </p>
                      </div>
                      <span className="text-2xs font-mono bg-black/[0.04] dark:bg-[var(--bg-base)] text-[#5A6478] dark:text-[var(--text-2)] px-2 py-1 rounded border border-black/5 dark:border-[var(--border)]">
                        Immutable
                      </span>
                    </div>

                    {/* Detected Hardware from Doctor */}
                    <div className="flex items-center justify-between border-b border-[#E5E2D9]/70 dark:border-[var(--border)] pb-2.5">
                      <div className="flex-1 pr-2">
                        <div className="flex items-center gap-2">
                          <span className="text-[13px] font-semibold text-[#14213D] dark:text-[var(--text-1)]">
                            Hardware Detection:
                          </span>
                        </div>
                        {hardwareCheck ? (
                          <div className="text-[12px] text-[#374151] dark:text-[var(--text-2)] mt-0.5 font-mono">
                            {Array.isArray(hardwareCheck.details)
                              ? hardwareCheck.details.join(' · ')
                              : String(hardwareCheck.details || 'Detected')}
                          </div>
                        ) : (
                          <p className="text-[12px] text-[#5A6478] dark:text-[var(--text-2)] mt-0.5 italic">
                            Run diagnostic probe to inspect local hardware and GPU acceleration
                          </p>
                        )}
                      </div>
                      <button 
                        onClick={handleRefreshHardware}
                        disabled={isDoctorRunning || isRefreshingHardware}
                        className="text-[12.5px] font-medium text-[#0F766E] dark:text-[var(--accent)] hover:underline flex items-center gap-1 cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none rounded-xs shrink-0 disabled:opacity-50" 
                        type="button" 
                        aria-label="Refresh Hardware"
                      >
                        <RefreshCw className={`w-3.5 h-3.5 ${isRefreshingHardware || isDoctorRunning ? 'animate-spin' : ''}`} aria-hidden="true" />
                        <span>{isRefreshingHardware || isDoctorRunning ? 'Probing...' : 'Refresh'}</span>
                      </button>
                    </div>

                    <div className="pt-0.5">
                      <div className="flex items-center justify-between text-[12px] mb-1">
                        <span className="font-medium text-[#14213D] dark:text-[var(--text-1)]">
                          Executable Location:
                        </span>
                      </div>
                      <div className="font-mono text-[11.5px] text-[#374151] dark:text-[var(--text-2)] truncate bg-[#F9F8F5] dark:bg-[var(--bg-base)] px-2.5 py-1.5 rounded border border-[#E5E2D9] dark:border-[var(--border)]">
                        {formData.llama_server_path || (formData.runtime_mode === 'managed' ? '%LOCALAPPDATA%\\AksaraSight\\runtimes\\llama-server.exe' : 'Custom llama-server path')}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Field 3: Start server automatically toggle (MUTABLE) */}
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
                    aria-checked={formData.auto_start_server}
                    aria-label="Start engine automatically with GUI"
                    onClick={() => setFormData((prev) => ({ ...prev, auto_start_server: !prev.auto_start_server }))}
                    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)] focus:ring-offset-2 ${
                      formData.auto_start_server ? 'bg-[#0F766E] dark:bg-[var(--accent)]' : 'bg-[#8A94A6] dark:bg-[var(--border-strong)]'
                    }`} 
                    type="button" 
                  >
                    <span 
                      className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white dark:bg-[#f0f1f3] shadow-sm ring-0 transition duration-200 ease-in-out ${
                        formData.auto_start_server ? 'translate-x-4' : 'translate-x-0'
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
                        Execute comprehensive hardware, runtime, reachability, and vision verification
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={handleRunDoctor}
                      disabled={isDoctorRunning}
                      className="h-8 px-3.5 bg-[#0F766E] dark:bg-[var(--accent)] hover:bg-[#115E59] dark:hover:bg-[var(--accent)]/90 active:bg-[#0d4f4b] text-white dark:text-[var(--bg-base)] rounded-lg text-[12px] font-semibold active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out flex items-center gap-1.5 cursor-pointer shadow-xs disabled:opacity-50"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${isDoctorRunning ? 'animate-spin' : ''}`} />
                      <span>{isDoctorRunning ? 'Probing...' : 'Run Doctor'}</span>
                    </button>
                  </div>

                  {doctorError && (
                    <div role="alert" className="p-2.5 bg-red-50 dark:bg-[var(--danger)]/10 border border-red-200 dark:border-[var(--danger)]/30 text-red-700 dark:text-[var(--danger)] rounded-lg text-xs">
                      {doctorError}
                    </div>
                  )}

                  {/* Doctor Real Verification Report */}
                  {doctorReport && (
                    <div className="p-3.5 bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#8A94A6]/30 dark:border-[var(--border)] text-[#14213D] dark:text-[var(--text-1)] shadow-xs rounded-lg font-mono text-[11.5px] leading-relaxed animate-fade-in space-y-2.5">
                      <div className="flex items-center justify-between border-b border-[#8A94A6]/20 dark:border-[var(--border)] pb-2 font-sans">
                        <span className="text-[#14213D] dark:text-[var(--text-1)] font-semibold text-[12.5px]">
                          Diagnostic Verification Report
                        </span>
                        <span className={`font-mono text-[11px] px-2 py-0.5 rounded font-semibold border ${
                          doctorReport.failed_checks === 0
                            ? 'bg-[#0F766E]/10 dark:bg-[var(--success)]/10 text-[#0F766E] dark:text-[var(--success)] border-[#0F766E]/20 dark:border-[var(--success)]/30'
                            : 'bg-red-500/10 text-red-700 dark:text-[var(--danger)] border-red-500/20'
                        }`}>
                          {doctorReport.status} ({doctorReport.total_checks - doctorReport.failed_checks}/{doctorReport.total_checks} PASS)
                        </span>
                      </div>
                      <div className="space-y-2">
                        {doctorReport.checks?.map((res, idx) => (
                          <div key={idx} className="border-b border-[#8A94A6]/20 dark:border-[var(--border)] last:border-b-0 pb-2 pt-0.5">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-1.5">
                                <span className={`font-bold font-mono ${
                                  res.status === 'PASS' 
                                    ? 'text-[#0F766E] dark:text-[var(--success)]' 
                                    : res.status === 'WARN' 
                                      ? 'text-amber-600 dark:text-[var(--warning)]' 
                                      : 'text-red-600 dark:text-[var(--danger)]'
                                }`}>
                                  [{res.status}]
                                </span>
                                <span className="text-[#14213D] dark:text-[var(--text-1)] font-semibold">
                                  {res.title || res.category}
                                </span>
                              </div>
                              {res.category && res.title && res.title !== res.category && (
                                <span className="text-2xs text-[#5A6478] dark:text-[var(--text-2)] font-sans">
                                  {res.category}
                                </span>
                              )}
                            </div>

                            {res.details && (
                              <div className="pl-6 pt-1 text-[#5A6478] dark:text-[var(--text-2)] font-mono text-[11.5px] space-y-0.5">
                                {Array.isArray(res.details) ? (
                                  res.details.map((d, dIdx) => <div key={dIdx}>{d}</div>)
                                ) : (
                                  <div>{res.details}</div>
                                )}
                              </div>
                            )}

                            {res.remediation && (
                              <div className="pl-6 pt-1 text-amber-700 dark:text-[var(--warning)] font-sans text-[11px] flex items-center gap-1">
                                <span className="font-semibold">Remediation:</span>
                                <span>{res.remediation}</span>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* TAB 2: Processing & Quality (MUTABLE FIELDS) */}
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
                      {formData.dpi} DPI
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
                      className="w-full h-1.5 rounded-lg appearance-none cursor-pointer accent-[#0F766E] dark:accent-[var(--accent)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2" 
                    />
                  </div>

                  {/* Snapped Steps Label Row */}
                  <div className="flex justify-between items-center text-[12px] font-medium text-[#5A6478] dark:text-[var(--text-2)] px-0.5" style={{ fontVariantNumeric: 'tabular-nums' }}>
                    {DPI_STEPS.map((stepDpi) => (
                      <button 
                        key={stepDpi}
                        type="button"
                        onClick={() => setFormData((prev) => ({ ...prev, dpi: stepDpi }))}
                        className={`cursor-pointer transition-colors bg-transparent border-0 pb-0.5 ${
                          formData.dpi === stepDpi 
                            ? 'text-[#0F766E] dark:text-[var(--accent)] font-bold border-b-2 border-[#0F766E] dark:border-[var(--accent)]' 
                            : 'border-b-2 border-transparent hover:text-[#14213D] dark:hover:text-[var(--text-1)]'
                        }`}
                      >
                        {stepDpi} DPI
                      </button>
                    ))}
                  </div>

                  {/* Timing & Quality Guide */}
                  <div className="grid grid-cols-2 gap-2 text-[12px] pt-1">
                    <div className={`p-2 rounded border ${formData.dpi === 72 ? 'bg-[#0F766E]/10 dark:bg-[var(--accent)]/10 border-[#0F766E]/40 dark:border-[var(--accent)]/40 font-semibold text-[#0F766E] dark:text-[var(--accent)]' : 'bg-[#FAF9F5] dark:bg-[var(--bg-base)] border-[#8A94A6]/20 dark:border-[var(--border)] text-[#374151] dark:text-[var(--text-2)]'}`}>
                      72 DPI: Draft / Fast preview
                    </div>
                    <div className={`p-2 rounded border ${formData.dpi === 100 ? 'bg-[#0F766E]/10 dark:bg-[var(--accent)]/10 border-[#0F766E]/40 dark:border-[var(--accent)]/40 font-semibold text-[#0F766E] dark:text-[var(--accent)]' : 'bg-[#FAF9F5] dark:bg-[var(--bg-base)] border-[#8A94A6]/20 dark:border-[var(--border)] text-[#374151] dark:text-[var(--text-2)]'}`}>
                      100 DPI: Standard documents (Recommended)
                    </div>
                    <div className={`p-2 rounded border ${formData.dpi === 150 ? 'bg-[#0F766E]/10 dark:bg-[var(--accent)]/10 border-[#0F766E]/40 dark:border-[var(--accent)]/40 font-semibold text-[#0F766E] dark:text-[var(--accent)]' : 'bg-[#FAF9F5] dark:bg-[var(--bg-base)] border-[#8A94A6]/20 dark:border-[var(--border)] text-[#374151] dark:text-[var(--text-2)]'}`}>
                      150 DPI: High resolution / Small fonts
                    </div>
                    <div className={`p-2 rounded border ${formData.dpi === 200 ? 'bg-[#0F766E]/10 dark:bg-[var(--accent)]/10 border-[#0F766E]/40 dark:border-[var(--accent)]/40 font-semibold text-[#0F766E] dark:text-[var(--accent)]' : 'bg-[#FAF9F5] dark:bg-[var(--bg-base)] border-[#8A94A6]/20 dark:border-[var(--border)] text-[#374151] dark:text-[var(--text-2)]'}`}>
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
                        min={256}
                        max={8192}
                        value={formData.max_image_dimension}
                        onChange={(e) => setFormData((prev) => ({ ...prev, max_image_dimension: Number(e.target.value) }))}
                        className="w-full max-w-[120px] h-[34px] px-2.5 text-[13.5px] bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md text-[#14213D] dark:text-[var(--text-1)] focus:outline-none focus:border-[#0F766E] dark:focus:border-[var(--accent)] focus:ring-1 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)]" 
                      />
                      <span className="text-[12px] text-[#4B5563] dark:text-[var(--text-2)]">px</span>
                    </div>
                    <p className="text-[11.5px] text-[#4B5563] dark:text-[var(--text-2)] mt-1">
                      Images exceeding this dimension are downscaled before inference
                    </p>
                  </div>

                  <div>
                    <label className="block text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)] mb-1" htmlFor="max-tokens">
                      Max Tokens Per Page
                    </label>
                    <input 
                      id="max-tokens" 
                      type="number" 
                      min={128}
                      max={16384}
                      value={formData.max_tokens}
                      onChange={(e) => setFormData((prev) => ({ ...prev, max_tokens: Number(e.target.value) }))}
                      className="w-full max-w-[120px] h-[34px] px-2.5 text-[13.5px] bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md text-[#14213D] dark:text-[var(--text-1)] focus:outline-none focus:border-[#0F766E] dark:focus:border-[var(--accent)] focus:ring-1 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)]" 
                    />
                    <p className="text-[11.5px] text-[#4B5563] dark:text-[var(--text-2)] mt-1">
                      Context window token budget reserved for each page's OCR output
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* TAB 3: Advanced & Network */}
            {activeCategory === 'advanced' && (
              <div className="space-y-4 animate-fade-in" role="tabpanel">
                <div className="bg-white dark:bg-[var(--bg-elevated)] p-4 rounded-lg border border-[#E5E2D9] dark:border-[var(--border)] space-y-3.5 transition-colors">
                  
                  {/* Local Engine HTTP Endpoint URL (IMMUTABLE - READ ONLY) */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)]" htmlFor="endpoint">
                        Local Engine HTTP Endpoint URL
                      </label>
                      <span className="inline-flex items-center gap-1 text-[11px] font-medium font-mono text-[#5A6478] dark:text-[var(--text-2)] bg-black/[0.04] dark:bg-[var(--bg-elevated)] px-2 py-0.5 rounded border border-black/5 dark:border-[var(--border)]">
                        <Lock className="w-3 h-3 text-[#5A6478] dark:text-[var(--text-2)]" aria-hidden="true" />
                        <span>Read-Only</span>
                      </span>
                    </div>
                    <div className="w-full h-[34px] px-3 font-mono text-[12.5px] bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md text-[#14213D] dark:text-[var(--text-1)] flex items-center justify-between">
                      <span>{formData.local_endpoint}</span>
                      <span className="text-2xs text-[#5A6478] dark:text-[var(--text-2)]">Strict Loopback</span>
                    </div>
                  </div>

                  {/* Allow Remote Endpoints (IMMUTABLE - READ ONLY GUARANTEE) */}
                  <div className="flex items-center justify-between pt-2 border-t border-[#8A94A6]/20 dark:border-[var(--border)]">
                    <div>
                      <span className="text-[13px] font-semibold text-[#14213D] dark:text-[var(--text-1)] flex items-center gap-1.5">
                        <ShieldCheck className="w-4 h-4 text-[#0F766E] dark:text-[var(--success)]" />
                        <span>100% Local-Only Invariant</span>
                      </span>
                      <p className="text-[12px] text-[#5A6478] dark:text-[var(--text-2)] mt-0.5">
                        Remote external endpoints forbidden. Offline confidential processing guaranteed.
                      </p>
                    </div>
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-[#0F766E]/10 dark:bg-[var(--success)]/10 text-[#0F766E] dark:text-[var(--success)] border border-[#0F766E]/20 text-xs font-semibold">
                      <span>Enforced Local</span>
                    </span>
                  </div>

                  {/* Mutable Network Limits: Timeout and Max Retries */}
                  <div className="grid grid-cols-2 gap-4 pt-2 border-t border-[#E5E2D9] dark:border-[var(--border)]">
                    <div>
                      <label className="block text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)] mb-1" htmlFor="req-timeout">
                        HTTP Request Timeout
                      </label>
                      <div className="flex items-center gap-2">
                        <input 
                          id="req-timeout" 
                          type="number" 
                          min={1}
                          max={600}
                          value={formData.timeout}
                          onChange={(e) => setFormData((prev) => ({ ...prev, timeout: Number(e.target.value) }))}
                          className="w-full max-w-[100px] h-[34px] px-2.5 text-[13.5px] bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md text-[#14213D] dark:text-[var(--text-1)] focus:outline-none focus:border-[#0F766E] dark:focus:border-[var(--accent)] focus:ring-1 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)]" 
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
                        min={0}
                        max={10}
                        value={formData.max_retries}
                        onChange={(e) => setFormData((prev) => ({ ...prev, max_retries: Number(e.target.value) }))}
                        className="w-full max-w-[100px] h-[34px] px-2.5 text-[13.5px] bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md text-[#14213D] dark:text-[var(--text-1)] focus:outline-none focus:border-[#0F766E] dark:focus:border-[var(--accent)] focus:ring-1 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)]" 
                      />
                    </div>
                  </div>

                  {/* Hugging Face Model Repository (IMMUTABLE - READ ONLY) */}
                  <div className="pt-2 border-t border-[#E5E2D9] dark:border-[var(--border)]">
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)]" htmlFor="model-repo">
                        Hugging Face Model Repository
                      </label>
                      <span className="inline-flex items-center gap-1 text-[11px] font-medium font-mono text-[#5A6478] dark:text-[var(--text-2)] bg-black/[0.04] dark:bg-[var(--bg-elevated)] px-2 py-0.5 rounded border border-black/5 dark:border-[var(--border)]">
                        <Lock className="w-3 h-3 text-[#5A6478] dark:text-[var(--text-2)]" aria-hidden="true" />
                        <span>Read-Only</span>
                      </span>
                    </div>
                    <div className="w-full h-[34px] px-3 font-mono text-[12.5px] bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md text-[#14213D] dark:text-[var(--text-1)] flex items-center justify-between">
                      <span>{formData.model_repo}</span>
                      <span className="text-2xs text-[#5A6478] dark:text-[var(--text-2)]">GLM-OCR Architecture</span>
                    </div>
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
              disabled={!isDirty || isSaving}
              className={`min-w-[124px] h-[34px] px-4 rounded-lg text-[13px] font-medium flex items-center justify-center gap-1.5 transition-all duration-150 ease-out focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] focus-visible:outline-none ${
                saveSuccess
                  ? 'bg-[#15803D] dark:bg-[var(--success)] text-white shadow-xs'
                  : isDirty 
                    ? 'bg-[#0F766E] dark:bg-[var(--accent)] text-white dark:text-[var(--bg-base)] hover:bg-[#115E59] dark:hover:bg-[var(--accent)]/90 shadow-xs cursor-pointer active:scale-[0.96] active:translate-y-px active:brightness-95' 
                    : 'bg-[#0F766E] dark:bg-[var(--accent)] text-white dark:text-[var(--bg-base)] opacity-40 cursor-not-allowed'
              }`} 
              type="button" 
            >
              {saveSuccess ? (
                <>
                  <CheckCircle2 className="w-4 h-4 animate-fade-in" />
                  <span>Saved!</span>
                </>
              ) : isSaving ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  <span>Saving...</span>
                </>
              ) : (
                <span>Save Settings</span>
              )}
            </button>
          </div>

        </div>
      </main>
    </div>
  );
};
