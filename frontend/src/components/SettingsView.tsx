import React, { useState, useEffect, useMemo, useRef } from 'react';
import { 
  CheckCircle2, 
  Cpu, 
  Sliders, 
  Terminal, 
  RefreshCw, 
  AlertTriangle, 
  Stethoscope,
  FolderOpen,
  Download,
  HardDrive
} from 'lucide-react';
import { BackendSettings, DoctorReport, EngineSettings, ModelStatusInfo, RuntimeStatusInfo } from '../types';

interface SettingsViewProps {
  settings?: EngineSettings;
  onSave?: (newSettings: BackendSettings) => void;
  onCancel?: () => void;
  modelStatus?: ModelStatusInfo | null;
  onDownloadModel?: () => void | Promise<void>;
  onCancelModelDownload?: () => void | Promise<void>;
  runtimeStatus?: RuntimeStatusInfo | null;
  onDownloadRuntime?: () => void | Promise<void>;
}

const formatBytes = (bytes: number): string => {
  if (!bytes || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(2)} ${units[i] || 'GB'}`;
};


type SettingsCategory = 'engine' | 'processing' | 'advanced';

const DPI_STEPS = [72, 100, 150, 200];

const DPI_OPTIONS: { dpi: number; desc: string }[] = [
  { dpi: 72, desc: 'Draft / Fast preview' },
  { dpi: 100, desc: 'Standard documents (Recommended)' },
  { dpi: 150, desc: 'High resolution / Small fonts' },
  { dpi: 200, desc: 'Archival / Fine manuscript detail' },
];

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
  'backend',
  'runtime_mode',
  'managed_backend_override',
  'llama_server_path',
  'local_endpoint',
  'allow_remote',
  'model_repo',
] as const;

export const SettingsView: React.FC<SettingsViewProps> = ({
  settings,
  onSave,
  onCancel,
  modelStatus,
  onDownloadModel,
  onCancelModelDownload,
  runtimeStatus: propRuntimeStatus,
  onDownloadRuntime,
}) => {
  const [internalModelStatus, setInternalModelStatus] = useState<ModelStatusInfo | null>(null);
  const effectiveModelStatus = useMemo(() => {
    if (!modelStatus && !internalModelStatus) return null;
    if (!modelStatus) return internalModelStatus;
    if (!internalModelStatus) return modelStatus;
    return {
      ...internalModelStatus,
      ...modelStatus,
      downloaded: modelStatus.downloaded || internalModelStatus.downloaded,
      is_downloading: modelStatus.is_downloading ?? internalModelStatus.is_downloading,
      percent: modelStatus.percent || internalModelStatus.percent,
      bytes_downloaded: modelStatus.bytes_downloaded || internalModelStatus.bytes_downloaded,
      active_file: modelStatus.active_file || internalModelStatus.active_file,
    };
  }, [modelStatus, internalModelStatus]);

  const [internalRuntimeStatus, setInternalRuntimeStatus] = useState<RuntimeStatusInfo | null>(null);
  const effectiveRuntimeStatus = propRuntimeStatus !== undefined ? propRuntimeStatus : internalRuntimeStatus;
  const [isStartingRuntimeDownload, setIsStartingRuntimeDownload] = useState(false);
  const [isStartingModelDownload, setIsStartingModelDownload] = useState(false);

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
      ...(settings?.allow_remote !== undefined ? { allow_remote: settings.allow_remote } : {}),
      ...(settings?.allowRemote !== undefined ? { allow_remote: settings.allowRemote } : {}),
    };
  });

  const [savedSettings, setSavedSettings] = useState<BackendSettings | null>(null);
  const [activeCategory, setActiveCategory] = useState<SettingsCategory>('engine');
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const saveToastTimerRef = useRef<NodeJS.Timeout | number | null>(null);

  useEffect(() => {
    return () => {
      if (saveToastTimerRef.current) {
        clearTimeout(saveToastTimerRef.current);
      }
    };
  }, []);

  // Diagnostic (--doctor) state
  const [isDoctorRunning, setIsDoctorRunning] = useState(false);
  const [isRefreshingHardware, setIsRefreshingHardware] = useState(false);
  const [doctorReport, setDoctorReport] = useState<DoctorReport | null>(null);
  const [doctorError, setDoctorError] = useState<string | null>(null);

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

  const handleToggleRemote = () => {
    if (!formData.allow_remote) {
      setShowSecurityWarning(true);
    } else {
      setFormData((prev) => ({ ...prev, allow_remote: false }));
    }
  };

  // Sliding segmented indicators for Runtime Mode and Managed Backend Override
  const [runtimeIndicator, setRuntimeIndicator] = useState<{ left: number; width: number }>({ left: 2, width: 0 });
  const runtimeContainerRef = useRef<HTMLDivElement>(null);
  const runtimeRefs = useRef<{ [key: string]: HTMLButtonElement | null }>({});

  const [targetIndicator, setTargetIndicator] = useState<{ left: number; width: number }>({ left: 2, width: 0 });
  const targetContainerRef = useRef<HTMLDivElement>(null);
  const targetRefs = useRef<{ [key: string]: HTMLButtonElement | null }>({});

  useEffect(() => {
    const updateIndicators = () => {
      const currentRuntime = formData.runtime_mode || 'managed';
      if (runtimeContainerRef.current && runtimeRefs.current[currentRuntime]) {
        const cRect = runtimeContainerRef.current.getBoundingClientRect();
        const tRect = runtimeRefs.current[currentRuntime]!.getBoundingClientRect();
        setRuntimeIndicator({ left: tRect.left - cRect.left, width: tRect.width });
      }
      const currentTarget = formData.managed_backend_override || 'auto';
      if (currentRuntime === 'managed' && targetContainerRef.current && targetRefs.current[currentTarget]) {
        const cRect = targetContainerRef.current.getBoundingClientRect();
        const tRect = targetRefs.current[currentTarget]!.getBoundingClientRect();
        setTargetIndicator({ left: tRect.left - cRect.left, width: tRect.width });
      }
    };
    updateIndicators();
    window.addEventListener('resize', updateIndicators);
    return () => window.removeEventListener('resize', updateIndicators);
  }, [formData.runtime_mode, formData.managed_backend_override, activeCategory, savedSettings]);

  const handleBrowseExecutable = async () => {
    try {
      const res = await fetch('/api/dialog/file', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        if (data?.path) {
          setFormData((prev) => ({ ...prev, llama_server_path: data.path }));
        }
      }
    } catch (err) {
      console.error('Failed to open file dialog:', err);
    }
  };

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

    // 3. Fetch model status from GET /api/model/status if not provided
    if (modelStatus === undefined) {
      fetch('/api/model/status')
        .then(async (res) => {
          if (res.ok) {
            const data: ModelStatusInfo = await res.json();
            if (isMounted && data) {
              setInternalModelStatus(data);
            }
          }
        })
        .catch(() => {});
    }

    return () => {
      isMounted = false;
    };
  }, [modelStatus]);

  // Model download & cancel handlers
  const handleDownloadModelAction = async () => {
    if (isStartingModelDownload || effectiveModelStatus?.is_downloading) return;
    if (effectiveModelStatus?.downloaded && !window.confirm('Model weights are already verified and installed locally. Do you want to re-download the ~1.4 GB model from Hugging Face?')) return;
    setIsStartingModelDownload(true);
    try {
      if (onDownloadModel) {
        await onDownloadModel();
      } else {
        await fetch('/api/model/download', { method: 'POST' });
        const res = await fetch('/api/model/status');
        if (res.ok) {
          const data: ModelStatusInfo = await res.json();
          setInternalModelStatus(data);
        }
      }
    } catch (err) {
      console.error('Failed to trigger model download:', err);
    } finally {
      setIsStartingModelDownload(false);
    }
  };

  const handleCancelModelDownloadAction = async () => {
    if (onCancelModelDownload) {
      await onCancelModelDownload();
    } else {
      try {
        await fetch('/api/model/download/cancel', { method: 'POST' });
        const res = await fetch('/api/model/status');
        if (res.ok) {
          const data: ModelStatusInfo = await res.json();
          setInternalModelStatus(data);
        }
      } catch (err) {
        console.error('Failed to cancel model download:', err);
      }
    }
  };

  // Fetch runtime status and subscribe to SSE progress events
  useEffect(() => {
    let isMounted = true;

    if (propRuntimeStatus === undefined) {
      fetch('/api/runtime/status')
        .then(async (res) => {
          if (res.ok) {
            const data: RuntimeStatusInfo = await res.json();
            if (isMounted && data) {
              setInternalRuntimeStatus(data);
            }
          }
        })
        .catch((err) => {
          console.warn('Could not fetch /api/runtime/status:', err);
        });
    }

    const eventSource = (typeof window !== 'undefined' && (window as any).__eventSource)
      ? (window as any).__eventSource
      : (typeof EventSource !== 'undefined' ? new EventSource('/api/events') : null);

    if (!eventSource) return;

    const handleRuntimeProgress = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        if (isMounted) {
          setInternalRuntimeStatus((prev) => ({
            ...prev,
            ...data,
            installed: data.installed ?? prev?.installed ?? false,
            is_downloading: data.is_downloading ?? true,
            bytes_downloaded: data.bytes_downloaded ?? prev?.bytes_downloaded ?? 0,
            total_bytes: data.total_bytes ?? prev?.total_bytes ?? 0,
            percent: data.percent ?? prev?.percent ?? 0,
            message: data.message ?? prev?.message ?? '',
            executable_path: data.executable_path ?? prev?.executable_path ?? null,
            expected_path: data.expected_path ?? prev?.expected_path ?? '',
            error: data.error ?? null,
          }));
        }
      } catch (err) {
        console.error('Error handling runtime_download_progress event', err);
      }
    };

    const handleModelProgress = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        if (isMounted) {
          const isComplete = data.status === 'completed' || (!data.is_downloading && (data.percent ?? 0) >= 100);
          setInternalModelStatus((prev) => ({
            repo: data.repo || prev?.repo || 'ggml-org/GLM-OCR-GGUF',
            revision: data.revision || prev?.revision || 'main',
            downloaded: isComplete || data.downloaded === true || (prev?.downloaded ?? false),
            model_path: data.model_path ?? prev?.model_path ?? null,
            mmproj_path: data.mmproj_path ?? prev?.mmproj_path ?? null,
            total_bytes: data.total_bytes ?? prev?.total_bytes ?? 0,
            is_downloading: data.is_downloading ?? !isComplete,
            bytes_downloaded: data.bytes_downloaded ?? prev?.bytes_downloaded ?? 0,
            percent: data.percent ?? prev?.percent ?? 0,
            active_file: data.active_file ?? prev?.active_file ?? null,
            error: data.error ?? null,
          }));
          if (isComplete) {
            fetch('/api/model/status')
              .then((res) => (res.ok ? res.json() : null))
              .then((fresh) => {
                if (isMounted && fresh) setInternalModelStatus(fresh);
              })
              .catch(() => {});
          }
        }
      } catch (err) {
        console.error('Error handling model_download_progress event in SettingsView', err);
      }
    };

    eventSource.addEventListener('runtime_download_progress', handleRuntimeProgress);
    eventSource.addEventListener('model_download_progress', handleModelProgress);

    return () => {
      isMounted = false;
      eventSource.removeEventListener('runtime_download_progress', handleRuntimeProgress);
      eventSource.removeEventListener('model_download_progress', handleModelProgress);
      if (typeof window !== 'undefined' && eventSource !== (window as any).__eventSource) {
        eventSource.close();
      }
    };
  }, [propRuntimeStatus]);

  // Runtime download handler
  const handleDownloadRuntimeAction = async () => {
    if (onDownloadRuntime) {
      await onDownloadRuntime();
    } else {
      setIsStartingRuntimeDownload(true);
      try {
        setInternalRuntimeStatus((prev) => (prev ? { ...prev, is_downloading: true, error: null } : null));
        const res = await fetch('/api/runtime/download', { method: 'POST' });
        if (res.ok) {
          const statusRes = await fetch('/api/runtime/status');
          if (statusRes.ok) {
            const data: RuntimeStatusInfo = await statusRes.json();
            setInternalRuntimeStatus(data);
          }
        } else {
          const errData = await res.json().catch(() => ({ detail: 'Failed to start runtime download' }));
          setInternalRuntimeStatus((prev) => (prev ? { ...prev, is_downloading: false, error: errData.detail || 'Failed to start download' } : null));
        }
      } catch (err: any) {
        console.error('Failed to trigger runtime download:', err);
        setInternalRuntimeStatus((prev) => (prev ? { ...prev, is_downloading: false, error: err?.message || 'Network error triggering download' } : null));
      } finally {
        setIsStartingRuntimeDownload(false);
      }
    }
  };


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
        // Re-fetch runtime status after settings change (e.g. backend override changed)
        fetch('/api/runtime/status')
          .then((r) => (r.ok ? r.json() : null))
          .then((d: RuntimeStatusInfo | null) => {
            if (d) setInternalRuntimeStatus(d);
          })
          .catch((err) => {
            console.warn('Failed to refresh runtime status after settings change:', err);
          });
        if (saveToastTimerRef.current) {
          clearTimeout(saveToastTimerRef.current);
        }
        saveToastTimerRef.current = setTimeout(() => {
          setSaveSuccess(false);
          saveToastTimerRef.current = null;
        }, 2500);
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
            
            {activeCategory === 'engine' && (
              <div className="space-y-4 animate-fade-in" role="tabpanel">
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
                            onChange={() => setFormData((prev) => ({ ...prev, backend: backendOption }))}
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
                        className="absolute top-0.5 bottom-0.5 rounded-md bg-white dark:bg-[var(--bg-elevated)] border border-[#14213D]/10 dark:border-[var(--border)] shadow-xs transition-all duration-200 ease-tactile pointer-events-none"
                        style={{
                          left: `${runtimeIndicator.left}px`,
                          width: `${runtimeIndicator.width}px`,
                          opacity: runtimeIndicator.width > 0 ? 1 : 0,
                        }}
                      />
                      <button 
                        ref={(el) => { runtimeRefs.current.managed = el; }}
                        type="button"
                        onClick={() => setFormData((prev) => ({ ...prev, runtime_mode: 'managed' }))}
                        className={`relative z-10 px-3 py-1 rounded-md text-[12px] font-medium whitespace-nowrap cursor-pointer active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] focus-visible:outline-none ${
                          formData.runtime_mode === 'managed' 
                            ? 'text-[#14213D] dark:text-[var(--text-1)]' 
                            : 'text-[#374151] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)]'
                        }`}
                      >
                        Managed Local Runtime
                      </button>
                      <button 
                        ref={(el) => { runtimeRefs.current.custom = el; }}
                        type="button"
                        onClick={() => setFormData((prev) => ({ ...prev, runtime_mode: 'custom' }))}
                        className={`relative z-10 px-3 py-1 rounded-md text-[12px] font-medium whitespace-nowrap cursor-pointer active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] focus-visible:outline-none ${
                          formData.runtime_mode === 'custom' 
                            ? 'text-[#14213D] dark:text-[var(--text-1)]' 
                            : 'text-[#374151] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)]'
                        }`}
                      >
                        Custom Executable Path
                      </button>
                    </div>
                  </div>

                  {formData.runtime_mode === 'managed' ? (
                    /* Managed Inset Block */
                    <div className="bg-white dark:bg-[var(--bg-elevated)] rounded-lg p-3.5 border border-[#E5E2D9] dark:border-[var(--border)] space-y-3 transition-colors animate-fade-in">
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

                      <div className="flex items-center justify-between">
                        <label className="text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)]">
                          Target Hardware Backend
                        </label>
                        <div 
                          ref={targetContainerRef}
                          className="relative inline-flex p-0.5 bg-[#F0EEE8] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-lg gap-1 whitespace-nowrap"
                        >
                          <div 
                            className="absolute top-0.5 bottom-0.5 rounded-md bg-white dark:bg-[var(--bg-elevated)] border border-[#14213D]/10 dark:border-[var(--border)] shadow-xs transition-all duration-200 ease-tactile pointer-events-none"
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
                              onClick={() => setFormData((prev) => ({ ...prev, managed_backend_override: backendOption }))}
                              className={`relative z-10 px-2.5 py-0.5 rounded text-[12px] font-medium whitespace-nowrap cursor-pointer active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] focus-visible:outline-none ${
                                (formData.managed_backend_override || 'auto') === backendOption 
                                  ? 'text-[#14213D] dark:text-[var(--text-1)]' 
                                  : 'text-[#374151] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)]'
                              }`}
                            >
                              {backendOption}
                            </button>
                          ))}
                        </div>
                      </div>

                      <div className="pt-0.5">
                        <div className="flex items-center justify-between text-[12px] mb-1">
                          <span className="font-medium text-[#14213D] dark:text-[var(--text-1)]">
                            Executable Location:
                          </span>
                          {effectiveRuntimeStatus?.installed ? (
                            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-[#15803D]/10 text-[#14532D] dark:bg-[var(--success)]/10 dark:text-[var(--success)] border border-[#15803D]/25 dark:border-[var(--success)]/30">
                              <CheckCircle2 className="w-3 h-3 text-[#15803D] dark:text-[var(--success)]" aria-hidden="true" />
                              Installed (Verified Local Binary)
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-amber-500/10 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400 border border-amber-500/25 dark:border-amber-500/30">
                              <AlertTriangle className="w-3 h-3 text-amber-600 dark:text-amber-400" aria-hidden="true" />
                              Not Installed
                            </span>
                          )}
                        </div>
                        <div className="font-mono text-[11.5px] text-[#374151] dark:text-[var(--text-2)] truncate bg-[#F9F8F5] dark:bg-[var(--bg-base)] px-2.5 py-1.5 rounded border border-[#E5E2D9] dark:border-[var(--border)]" title={effectiveRuntimeStatus?.executable_path || effectiveRuntimeStatus?.expected_path || ''}>
                          {effectiveRuntimeStatus?.executable_path || effectiveRuntimeStatus?.expected_path || `%LOCALAPPDATA%\\AksaraSight\\runtimes\\llama-cpp\\b11361-${formData.managed_backend_override || 'auto'}\\llama-server.exe`}
                        </div>
                      </div>

                      {/* Error Alert */}
                      {effectiveRuntimeStatus?.error && (
                        <div role="alert" className="p-2.5 bg-red-50 dark:bg-[var(--danger)]/10 border border-red-200 dark:border-[var(--danger)]/30 text-red-700 dark:text-[var(--danger)] rounded-lg text-xs flex items-center gap-2">
                          <AlertTriangle className="w-4 h-4 shrink-0 text-red-600 dark:text-[var(--danger)]" aria-hidden="true" />
                          <span>{effectiveRuntimeStatus.error}</span>
                        </div>
                      )}

                      {/* Download Progress or Action Button */}
                      {effectiveRuntimeStatus?.is_downloading ? (
                        <div className="space-y-2 pt-1">
                          <div className="flex items-center justify-between text-xs">
                            <div className="flex items-center gap-1.5 font-mono text-[11.5px] text-[#374151] dark:text-[var(--text-2)] truncate max-w-[70%]">
                              <RefreshCw className="w-3.5 h-3.5 animate-spin text-[#0F766E] dark:text-[var(--accent)] shrink-0" aria-hidden="true" />
                              <span className="truncate">{effectiveRuntimeStatus.message || 'Downloading runtime...'}</span>
                              {effectiveRuntimeStatus?.total_parts && effectiveRuntimeStatus.total_parts > 1 ? (
                                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10.5px] font-sans font-medium bg-[#E5E2D9] dark:bg-[var(--border)] text-[#14213D] dark:text-[var(--text-1)] shrink-0">
                                  Part {effectiveRuntimeStatus.part || 1} of {effectiveRuntimeStatus.total_parts}
                                </span>
                              ) : null}
                            </div>
                            <div className="font-mono text-[11.5px] text-[#14213D] dark:text-[var(--text-1)] font-semibold shrink-0" style={{ fontVariantNumeric: 'tabular-nums' }}>
                              {effectiveRuntimeStatus.total_bytes > 0
                                ? `${formatBytes(effectiveRuntimeStatus.bytes_downloaded)} / ${formatBytes(effectiveRuntimeStatus.total_bytes)} (${Math.round(effectiveRuntimeStatus.percent)}%)`
                                : `${Math.round(effectiveRuntimeStatus.percent)}%`}
                            </div>
                          </div>

                          <div className="w-full bg-[#E5E2D9] dark:bg-[var(--bg-base)] h-2 rounded-full overflow-hidden relative">
                            <div
                              className="bg-[#0F766E] dark:bg-[var(--accent)] h-full transition-all duration-200 rounded-full relative overflow-hidden"
                              style={{ width: `${Math.min(100, Math.max(0, effectiveRuntimeStatus.percent))}%` }}
                            >
                              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/40 dark:via-white/30 to-transparent animate-shimmer" />
                            </div>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-center justify-between pt-1">
                          <div className="text-xs text-[#5A6478] dark:text-[var(--text-2)]">
                            {effectiveRuntimeStatus?.installed
                              ? 'Managed llama.cpp runtime binary is verified and ready.'
                              : 'Download the pinned llama.cpp build for local inference.'}
                          </div>
                          <button
                            type="button"
                            onClick={handleDownloadRuntimeAction}
                            disabled={isStartingRuntimeDownload}
                            className="h-8 px-3.5 bg-[#0F766E] dark:bg-[var(--accent)] hover:bg-[#115E59] dark:hover:bg-[var(--accent)]/90 active:bg-[#0d4f4b] text-white dark:text-[var(--bg-base)] rounded-lg text-xs font-semibold active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out flex items-center gap-1.5 cursor-pointer shadow-xs shrink-0 disabled:opacity-50"
                          >
                            <Download className="w-3.5 h-3.5" aria-hidden="true" />
                            <span>
                              {effectiveRuntimeStatus?.installed ? 'Re-download / Verify Runtime' : 'Download Runtime'}
                            </span>
                          </button>
                        </div>
                      )}
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
                            value={formData.llama_server_path || ''}
                            onChange={(e) => setFormData((prev) => ({ ...prev, llama_server_path: e.target.value }))}
                            placeholder="C:\tools\llama-cpp\llama-server.exe"
                            className="flex-1 h-[34px] px-3 font-mono text-[12px] bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md text-[#14213D] dark:text-[var(--text-1)] focus:outline-none focus:border-[#0F766E] dark:focus:border-[var(--accent)] focus:ring-1 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)]"
                          />
                          <button
                            type="button"
                            onClick={handleBrowseExecutable}
                            className="h-[34px] px-3 border border-[#8A94A6] dark:border-[var(--border)] hover:border-[#14213D] dark:hover:border-[var(--border-strong)] bg-white dark:bg-[var(--bg-elevated)] hover:bg-black/[0.02] dark:hover:bg-[var(--bg-active)] text-[#14213D] dark:text-[var(--text-1)] rounded-md text-[12.5px] font-medium transition-colors cursor-pointer flex items-center gap-1 focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] focus-visible:outline-none"
                            title="Browse local disk for llama-server executable"
                          >
                            <FolderOpen className="w-3.5 h-3.5 text-[#0F766E] dark:text-[var(--accent)]" />
                            <span>Browse...</span>
                          </button>
                        </div>
                        {formData.llama_server_path ? (
                          <p className="text-[11.5px] text-[#4B5563] dark:text-[var(--text-2)] mt-1.5 flex items-center gap-1.5">
                            <span className="w-2 h-2 rounded-full bg-[#15803D] dark:bg-[var(--success)]" />
                            <span>Custom llama-server binary configured</span>
                          </p>
                        ) : (
                          <p className="text-[11.5px] text-[#5A6478] dark:text-[var(--text-2)] mt-1.5">
                            Specify the full absolute path to a custom llama-server binary or browse to select one
                          </p>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* Model Weights Management Card */}
                <div className="bg-white dark:bg-[var(--bg-elevated)] p-4 rounded-lg border border-[#8A94A6]/25 dark:border-[var(--border)] space-y-3.5 transition-colors">
                  <div className="flex items-center justify-between border-b border-[#E5E2D9]/70 dark:border-[var(--border)] pb-2.5">
                    <div>
                      <div className="flex items-center gap-2">
                        <HardDrive className="w-4 h-4 text-[#0F766E] dark:text-[var(--accent)]" aria-hidden="true" />
                        <span className="text-[13.5px] font-semibold text-[#14213D] dark:text-[var(--text-1)]">
                          Model Weights Management
                        </span>
                      </div>
                      <p className="text-[12px] text-[#5A6478] dark:text-[var(--text-2)] mt-0.5">
                        Offline GGUF vision-language model weights for local OCR processing
                      </p>
                    </div>

                    {/* Status Badge */}
                    <div>
                      {effectiveModelStatus?.downloaded ? (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-[#15803D]/10 text-[#14532D] dark:bg-[var(--success)]/10 dark:text-[var(--success)] border border-[#15803D]/25 dark:border-[var(--success)]/30">
                          <CheckCircle2 className="w-3.5 h-3.5 text-[#15803D] dark:text-[var(--success)]" aria-hidden="true" />
                          Downloaded (Verified Local Weights)
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-amber-500/10 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400 border border-amber-500/25 dark:border-amber-500/30">
                          <AlertTriangle className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" aria-hidden="true" />
                          Not Downloaded (Using -hf fallback)
                        </span>
                      )}
                    </div>

                  </div>

                  {/* Model Metadata Grid */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs bg-[#FAF9F5] dark:bg-[var(--bg-base)] p-3 rounded-lg border border-[#E5E2D9] dark:border-[var(--border)]">
                    <div>
                      <span className="text-[#5A6478] dark:text-[var(--text-2)] block font-medium mb-0.5">Model</span>
                      <span className="font-semibold text-[#14213D] dark:text-[var(--text-1)] font-mono text-[12.5px]">
                        GLM-OCR (Q8_0)
                      </span>
                    </div>
                    <div>
                      <span className="text-[#5A6478] dark:text-[var(--text-2)] block font-medium mb-0.5">Repo & Revision</span>
                      <span className="font-medium text-[#14213D] dark:text-[var(--text-1)] font-mono text-[11.5px] truncate block" title={`${effectiveModelStatus?.repo || 'ggml-org/GLM-OCR-GGUF'} (Revision ${effectiveModelStatus?.revision || '65a42de'})`}>
                        {effectiveModelStatus?.repo || 'ggml-org/GLM-OCR-GGUF'} (Revision {effectiveModelStatus?.revision || '65a42de'})
                      </span>
                    </div>
                    <div>
                      <span className="text-[#5A6478] dark:text-[var(--text-2)] block font-medium mb-0.5">Size</span>
                      <span className="font-semibold text-[#14213D] dark:text-[var(--text-1)] font-mono text-[12.5px]">
                        1.34 GB
                      </span>
                    </div>
                  </div>

                  {/* Error banner if download had error */}
                  {effectiveModelStatus?.error && (
                    <div role="alert" className="p-2.5 bg-red-50 dark:bg-[var(--danger)]/10 border border-red-200 dark:border-[var(--danger)]/30 text-red-700 dark:text-[var(--danger)] rounded-lg text-xs flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4 shrink-0 text-red-600 dark:text-[var(--danger)]" aria-hidden="true" />
                      <span>{effectiveModelStatus.error}</span>
                    </div>
                  )}

                  {/* Download Progress or Action Button */}
                  {effectiveModelStatus?.is_downloading ? (
                    <div className="space-y-2 pt-1">
                      <div className="flex items-center justify-between text-xs">
                        <div className="flex items-center gap-1.5 font-mono text-[11.5px] text-[#374151] dark:text-[var(--text-2)] truncate max-w-[65%]">
                          <RefreshCw className="w-3.5 h-3.5 animate-spin text-[#0F766E] dark:text-[var(--accent)] shrink-0" aria-hidden="true" />
                          <span className="truncate">{effectiveModelStatus.active_file || 'Downloading weights...'}</span>
                        </div>
                        <div className="font-mono text-[11.5px] text-[#14213D] dark:text-[var(--text-1)] font-semibold shrink-0" style={{ fontVariantNumeric: 'tabular-nums' }}>
                          {formatBytes(effectiveModelStatus.bytes_downloaded)} / {formatBytes(effectiveModelStatus.total_bytes || 1440000000)} ({Math.round(effectiveModelStatus.percent)}%)
                        </div>
                      </div>

                      {/* Progress bar */}
                      <div className="w-full bg-[#E5E2D9] dark:bg-[var(--bg-base)] h-2 rounded-full overflow-hidden relative">
                        <div
                          className="bg-[#0F766E] dark:bg-[var(--accent)] h-full transition-all duration-200 rounded-full relative overflow-hidden"
                          style={{ width: `${effectiveModelStatus.percent}%` }}
                        >
                          <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/40 dark:via-white/30 to-transparent animate-shimmer" />
                        </div>
                      </div>

                      <div className="flex justify-end pt-1">
                        <button
                          type="button"
                          onClick={handleCancelModelDownloadAction}
                          className="h-7 px-3 bg-red-600 hover:bg-red-700 active:bg-red-800 text-white rounded-md text-xs font-semibold active:scale-[0.96] transition-all duration-150 cursor-pointer shadow-2xs"
                        >
                          Cancel Download
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between pt-1">
                      <div className="text-xs text-[#5A6478] dark:text-[var(--text-2)]">
                        {effectiveModelStatus?.downloaded ? (
                          <div className="flex items-center gap-1.5 text-[#15803D] dark:text-[var(--success)] font-medium">
                            <CheckCircle2 className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                            <span>Model verified & ready for offline inference.</span>
                          </div>
                        ) : (
                          <span>Download pinned weights to run OCR without online Hugging Face hub requests.</span>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={handleDownloadModelAction}
                        className="h-8 px-3.5 bg-[#0F766E] dark:bg-[var(--accent)] hover:bg-[#115E59] dark:hover:bg-[var(--accent)]/90 active:bg-[#0d4f4b] text-white dark:text-[var(--bg-base)] rounded-lg text-xs font-semibold active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out flex items-center gap-1.5 cursor-pointer shadow-xs shrink-0"
                      >
                        <Download className="w-3.5 h-3.5" aria-hidden="true" />
                        <span>
                          {effectiveModelStatus?.downloaded ? 'Re-download Weights' : 'Download Pinned Model'}
                        </span>
                      </button>
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-between bg-white dark:bg-[var(--bg-elevated)] p-3.5 rounded-lg border border-[#8A94A6]/25 dark:border-[var(--border)] transition-colors">
                  <div>
                    <span className="text-[13.5px] font-semibold text-[#14213D] dark:text-[var(--text-1)] block">
                      Start engine automatically with Web UI
                    </span>
                    <p className="text-[12px] text-[#5A6478] dark:text-[var(--text-2)] mt-0.5">
                      Spawn background llama-server process on workspace startup
                    </p>
                  </div>
                  <button 
                    role="switch" 
                    aria-checked={formData.auto_start_server}
                    aria-label="Start engine automatically with Web UI"
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

                <div className="bg-white dark:bg-[var(--bg-elevated)] p-3.5 rounded-lg border border-[#8A94A6]/25 dark:border-[var(--border)] space-y-3 transition-colors">
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-[13.5px] font-semibold text-[#14213D] dark:text-[var(--text-1)] flex items-center gap-1.5">
                        <Stethoscope className="w-4 h-4 text-[#0F766E] dark:text-[var(--accent)]" />
                        <span>System Diagnostic Probe</span>
                      </span>
                      <p className="text-[12px] text-[#5A6478] dark:text-[var(--text-2)] mt-0.5">
                        Test hardware, runtime, backend reachability, and vision inference
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

            {activeCategory === 'processing' && (
              <div className="space-y-4 animate-fade-in" role="tabpanel">
                
                {/* DPI Selection Block */}
                <div className="bg-white dark:bg-[var(--bg-elevated)] p-4 rounded-lg border border-[#8A94A6]/25 dark:border-[var(--border)] space-y-3 transition-colors">
                  <div className="flex justify-between items-center">
                    <div>
                      <h3 className="text-[13.5px] font-semibold text-[#14213D] dark:text-[var(--text-1)]">
                        Document Render Resolution (DPI)
                      </h3>
                      <p className="text-[11.5px] text-[#5A6478] dark:text-[var(--text-2)] mt-0.5">
                        Default rasterization resolution for OCR scans. Synchronized across workspace scan options.
                      </p>
                    </div>
                    <span 
                      className="font-mono text-[12.5px] font-bold text-[#0F766E] dark:text-[var(--accent)] px-2.5 py-0.5 rounded bg-[#0F766E]/10 dark:bg-[var(--accent)]/10 border border-[#0F766E]/25 dark:border-[var(--accent)]/30" 
                      style={{ fontVariantNumeric: 'tabular-nums' }}
                    >
                      {formData.dpi} DPI
                    </span>
                  </div>

                  {/* Interactive DPI Preset Cards */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 pt-1" role="group" aria-label="Document Render Resolution">
                    {DPI_OPTIONS.map((option) => {
                      const isSelected = formData.dpi === option.dpi;
                      return (
                        <button
                          key={option.dpi}
                          type="button"
                          aria-pressed={isSelected}
                          aria-label={`${option.dpi} DPI`}
                          onClick={() => setFormData((prev) => ({ ...prev, dpi: option.dpi }))}
                          className={`p-3 rounded-lg border text-left cursor-pointer transition-all duration-150 flex flex-col justify-between focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] active:scale-[0.98] ${
                            isSelected
                              ? 'bg-[#0F766E]/10 dark:bg-[var(--accent)]/10 border-[#0F766E] dark:border-[var(--accent)] ring-1 ring-[#0F766E]/30 dark:ring-[var(--accent)]/30 shadow-xs'
                              : 'bg-[#FAF9F5] dark:bg-[var(--bg-base)] border-[#8A94A6]/20 dark:border-[var(--border)] hover:border-[#8A94A6]/40 dark:hover:border-[#5A6478]'
                          }`}
                        >
                          <div className="flex items-center justify-between mb-1">
                            <span className={`font-mono text-[13px] font-bold ${
                              isSelected
                                ? 'text-[#0F766E] dark:text-[var(--accent)]'
                                : 'text-[#14213D] dark:text-[var(--text-1)]'
                            }`}>
                              {option.dpi} DPI
                            </span>
                            <div className={`w-3.5 h-3.5 rounded-full border flex items-center justify-center transition-colors ${
                              isSelected
                                ? 'border-[#0F766E] dark:border-[var(--accent)] bg-[#0F766E] dark:bg-[var(--accent)]'
                                : 'border-[#8A94A6]/40 dark:border-[var(--border)] bg-transparent'
                            }`}>
                              {isSelected && (
                                <div className="w-1.5 h-1.5 rounded-full bg-white dark:bg-[#121417]" />
                              )}
                            </div>
                          </div>
                          <span className={`text-[11.5px] leading-relaxed ${
                            isSelected
                              ? 'text-[#0F766E]/90 dark:text-[var(--accent)]/90 font-medium'
                              : 'text-[#5A6478] dark:text-[var(--text-2)]'
                          }`}>
                            {option.desc}
                          </span>
                        </button>
                      );
                    })}
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
                        min={512}
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

            {activeCategory === 'advanced' && (
              <div className="space-y-4 animate-fade-in" role="tabpanel">
                <div className="bg-white dark:bg-[var(--bg-elevated)] p-4 rounded-lg border border-[#E5E2D9] dark:border-[var(--border)] space-y-3.5 transition-colors">
                  
                  {/* Local Engine HTTP Endpoint URL */}
                  <div>
                    <label className="block text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)] mb-1" htmlFor="endpoint">
                      Local Engine HTTP Endpoint URL
                    </label>
                    <input 
                      id="endpoint" 
                      type="text" 
                      value={formData.local_endpoint}
                      onChange={(e) => setFormData((prev) => ({ ...prev, local_endpoint: e.target.value }))}
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
                      aria-checked={formData.allow_remote || false}
                      aria-label="Allow Non-Loopback (Remote) Endpoints"
                      onClick={handleToggleRemote}
                      className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)] focus:ring-offset-2 ${
                        formData.allow_remote ? 'bg-[#0F766E] dark:bg-[var(--accent)]' : 'bg-[#8A94A6] dark:bg-[var(--border-strong)]'
                      }`} 
                      type="button" 
                    >
                      <span 
                        className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white dark:bg-[#f0f1f3] shadow-sm ring-0 transition duration-200 ease-in-out ${
                          formData.allow_remote ? 'translate-x-4' : 'translate-x-0'
                        }`} 
                      />
                    </button>
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

                  {/* Hugging Face Model Repository */}
                  <div className="pt-2 border-t border-[#E5E2D9] dark:border-[var(--border)]">
                    <label className="block text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)] mb-1" htmlFor="model-repo">
                      Hugging Face Model Repository
                    </label>
                    <input 
                      id="model-repo" 
                      type="text" 
                      value={formData.model_repo}
                      onChange={(e) => setFormData((prev) => ({ ...prev, model_repo: e.target.value }))}
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
                  setFormData((prev) => ({ ...prev, allow_remote: true }));
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
