import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Cpu, Sliders, Terminal, RefreshCw, CheckCircle2, AlertTriangle } from 'lucide-react';
import { BackendSettings, EngineSettings, ModelStatusInfo, RuntimeStatusInfo } from '../../types';
import { useToast } from '../../hooks/useToast';
import { SettingsEngineTab } from './SettingsEngineTab';
import { SettingsProcessingTab } from './SettingsProcessingTab';
import { SettingsAdvancedTab } from './SettingsAdvancedTab';
import { useSettingsLifecycle } from './useSettingsLifecycle';
import { MUTABLE_KEYS, buildInitialFormData } from './settingsDefaults';

export interface SettingsViewProps {
  settings?: EngineSettings;
  onSave?: (newSettings: BackendSettings) => void;
  onCancel?: () => void;
  modelStatus?: ModelStatusInfo | null;
  onDownloadModel?: () => void | Promise<void>;
  onCancelModelDownload?: () => void | Promise<void>;
  runtimeStatus?: RuntimeStatusInfo | null;
  onDownloadRuntime?: () => void | Promise<void>;
}

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
  const { toast } = useToast();
  const isMountedRef = useRef(true);
  const saveToastTimerRef = useRef<any>(null);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      if (saveToastTimerRef.current) clearTimeout(saveToastTimerRef.current);
    };
  }, []);

  const [formData, setFormData] = useState<BackendSettings>(() => buildInitialFormData(settings));
  const [savedSettings, setSavedSettings] = useState<BackendSettings | null>(null);
  const [activeCategory, setActiveCategory] = useState<'engine' | 'processing' | 'advanced'>('engine');
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isDoctorRunning, setIsDoctorRunning] = useState(false);
  const [isRefreshingHardware, setIsRefreshingHardware] = useState(false);
  const [doctorError, setDoctorError] = useState<string | null>(null);
  const [isStartingRuntimeDownload, setIsStartingRuntimeDownload] = useState(false);
  const [isStartingModelDownload, setIsStartingModelDownload] = useState(false);

  const {
    effectiveModelStatus,
    effectiveRuntimeStatus,
    doctorReport,
    setDoctorReport,
    setInternalModelStatus,
    setInternalRuntimeStatus,
    fetchRuntimeStatus,
  } = useSettingsLifecycle({
    propRuntimeStatus,
    modelStatus,
    setFormData,
    setSavedSettings,
    isMountedRef,
  });

  const isDirty = useMemo(() => {
    const baseline = savedSettings || formData;
    return MUTABLE_KEYS.some((key) => formData[key] !== baseline[key]);
  }, [formData, savedSettings]);

  const handleRunDoctor = async () => {
    setIsDoctorRunning(true);
    setDoctorError(null);
    try {
      const res = await fetch('/api/doctor', { method: 'POST' });
      if (res.ok) setDoctorReport(await res.json());
      else setDoctorError('Diagnostic failed');
    } catch (err: any) {
      setDoctorError(err?.message || 'Network error');
    } finally {
      if (isMountedRef.current) {
        setIsDoctorRunning(false);
        setIsRefreshingHardware(false);
      }
    }
  };

  const handleBrowseExecutable = async () => {
    try {
      const res = await fetch('/api/dialog/file', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        if (data?.path && isMountedRef.current) {
          setFormData((prev) => ({ ...prev, llama_server_path: data.path }));
        }
      }
    } catch (err) {
      console.error('Browse failed:', err);
    }
  };

  const handleDownloadModelAction = async () => {
    if (isStartingModelDownload || effectiveModelStatus?.is_downloading) return;
    if (
      effectiveModelStatus?.downloaded &&
      !window.confirm('Model weights are already verified and installed locally. Do you want to re-download the ~1.82 GB model from Hugging Face?')
    ) {
      return;
    }
    setIsStartingModelDownload(true);
    try {
      if (onDownloadModel) {
        await onDownloadModel();
      } else {
        await fetch('/api/model/download', { method: 'POST' });
        const res = await fetch('/api/model/status');
        if (res.ok && isMountedRef.current) {
          setInternalModelStatus(await res.json());
        }
      }
    } catch (err) {
      console.error('Model download error:', err);
    } finally {
      if (isMountedRef.current) {
        setIsStartingModelDownload(false);
      }
    }
  };

  const handleSave = async () => {
    const baseline = savedSettings || formData;
    const updates: Record<string, any> = {};
    for (const key of MUTABLE_KEYS) {
      if (formData[key] !== baseline[key]) updates[key] = formData[key];
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
        const updated = data.settings || { ...baseline, ...updates };
        if (isMountedRef.current) {
          setSavedSettings(updated);
          setFormData(updated);
          setSaveSuccess(true);
        }
        onSave?.(updated);
        await fetchRuntimeStatus();
        if (saveToastTimerRef.current) clearTimeout(saveToastTimerRef.current);
        saveToastTimerRef.current = setTimeout(() => {
          if (isMountedRef.current) setSaveSuccess(false);
        }, 2500);
      } else {
        const errData = await res.json().catch(() => ({ detail: 'Failed to update settings' }));
        if (isMountedRef.current) {
          setSaveError(errData.detail || `HTTP ${res.status}`);
        }
      }
    } catch (err: any) {
      if (isMountedRef.current) {
        setSaveError(err?.message || 'Network error');
      }
    } finally {
      if (isMountedRef.current) {
        setIsSaving(false);
      }
    }
  };

  const handleTabKeyDown = (e: React.KeyboardEvent) => {
    const categories: Array<'engine' | 'processing' | 'advanced'> = ['engine', 'processing', 'advanced'];
    const currentIndex = categories.indexOf(activeCategory);
    if (currentIndex === -1) return;

    let targetIndex: number | null = null;
    if (e.key === 'ArrowRight') {
      e.preventDefault();
      targetIndex = (currentIndex + 1) % categories.length;
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      targetIndex = (currentIndex - 1 + categories.length) % categories.length;
    } else if (e.key === 'Home') {
      e.preventDefault();
      targetIndex = 0;
    } else if (e.key === 'End') {
      e.preventDefault();
      targetIndex = categories.length - 1;
    }

    if (targetIndex !== null) {
      const nextCategory = categories[targetIndex];
      setActiveCategory(nextCategory);
      document.getElementById(`tab-${nextCategory}`)?.focus();
    }
  };

  return (
    <div className="flex-1 bg-[#202020] dark:bg-[var(--bg-base)] flex flex-col overflow-hidden min-h-0 transition-colors">
      <div className="flex-1 p-4 md:p-6 flex justify-center items-center overflow-hidden min-h-0">
        <div className="w-full max-w-[840px] h-full max-h-[660px] flex flex-col bg-[#272727] dark:bg-[var(--bg-surface)] rounded-sm border border-white/8 dark:border-[var(--border)] shadow-sm overflow-hidden transition-colors">
          <div className="border-b border-white/8 dark:border-[var(--border)] px-6 pt-4 pb-0 shrink-0 bg-[#272727] dark:bg-[var(--bg-surface)]">
            {saveError && (
              <div role="alert" className="mb-3 p-3 bg-red-500/10 border border-red-500/25 text-red-400 rounded-sm text-xs flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 shrink-0" />
                  <span>{saveError}</span>
                </div>
                <button type="button" onClick={() => setSaveError(null)} className="text-xs font-semibold underline cursor-pointer">
                  Dismiss
                </button>
              </div>
            )}
            <div className="flex items-center justify-between pb-3">
              <div>
                <h1 className="text-[16px] font-semibold text-[#F3F3F3] dark:text-[var(--text-1)]">
                  Engine & Quality Settings
                </h1>
                <p className="text-[12.5px] text-[#A6A6A6] dark:text-[var(--text-2)] mt-0.5">
                  Configure local llama-server runtime, inference targets, and OCR pipeline parameters
                </p>
              </div>
              {saveSuccess && (
                <div role="status" className="px-3 py-1.5 bg-emerald-500/15 border border-emerald-500/30 rounded-sm flex items-center gap-1.5 text-emerald-400 text-[12px] font-medium shadow-2xs">
                  <CheckCircle2 className="w-4 h-4" />
                  <span>Settings saved successfully</span>
                </div>
              )}
            </div>
            <div
              className="flex items-center gap-6 text-[13.5px] font-medium"
              role="tablist"
              aria-label="Settings categories"
              onKeyDown={handleTabKeyDown}
            >
              {(['engine', 'processing', 'advanced'] as const).map((cat) => (
                <button
                  key={cat}
                  id={`tab-${cat}`}
                  type="button"
                  role="tab"
                  aria-selected={activeCategory === cat}
                  aria-controls={`tabpanel-${cat}`}
                  tabIndex={activeCategory === cat ? 0 : -1}
                  onClick={() => setActiveCategory(cat)}
                  className={`pb-2.5 border-b-2 font-semibold flex items-center gap-1.5 cursor-pointer transition-colors ${
                    activeCategory === cat
                      ? 'border-[#60CDFF] text-[#60CDFF]'
                      : 'border-transparent text-[#A6A6A6] hover:text-[#F3F3F3]'
                  }`}
                >
                  {cat === 'engine' ? (
                    <>
                      <Cpu className="w-4 h-4" />
                      <span>Engine & Hardware</span>
                    </>
                  ) : cat === 'processing' ? (
                    <>
                      <Sliders className="w-4 h-4" />
                      <span>Processing & Quality</span>
                    </>
                  ) : (
                    <>
                      <Terminal className="w-4 h-4" />
                      <span>Advanced & Network</span>
                    </>
                  )}
                </button>
              ))}
            </div>
          </div>

          <div
            id={`tabpanel-${activeCategory}`}
            role="tabpanel"
            aria-labelledby={`tab-${activeCategory}`}
            tabIndex={0}
            className="flex-1 p-6 overflow-y-auto min-h-0 bg-[#202020]/40 space-y-4 focus:outline-none"
          >
            {activeCategory === 'engine' && (
              <SettingsEngineTab
                formData={formData}
                setFormData={setFormData}
                effectiveRuntimeStatus={effectiveRuntimeStatus}
                effectiveModelStatus={effectiveModelStatus}
                doctorReport={doctorReport}
                doctorError={doctorError}
                isDoctorRunning={isDoctorRunning}
                isRefreshingHardware={isRefreshingHardware}
                isStartingRuntimeDownload={isStartingRuntimeDownload}
                onRefreshHardware={() => { setIsRefreshingHardware(true); handleRunDoctor(); }}
                onRunDoctor={handleRunDoctor}
                onBrowseExecutable={handleBrowseExecutable}
                onDownloadRuntime={async () => {
                  if (onDownloadRuntime) {
                    await onDownloadRuntime();
                    return;
                  }
                  setIsStartingRuntimeDownload(true);
                  try {
                    const res = await fetch('/api/runtime/download', { method: 'POST' });
                    if (!res.ok) {
                      const errData = await res.json().catch(() => ({}));
                      const msg = errData.detail || errData.error || `Runtime download failed (HTTP ${res.status})`;
                      toast.error(msg);
                    } else {
                      const statusRes = await fetch('/api/runtime/status');
                      if (statusRes.ok && isMountedRef.current) {
                        setInternalRuntimeStatus(await statusRes.json());
                      }
                    }
                  } catch (err: any) {
                    toast.error(err?.message || 'Network error starting runtime download');
                  } finally {
                    if (isMountedRef.current) {
                      setIsStartingRuntimeDownload(false);
                    }
                  }
                }}
                onDownloadModel={handleDownloadModelAction}
                onCancelModelDownload={() => {
                  if (onCancelModelDownload) onCancelModelDownload();
                  else fetch('/api/model/download/cancel', { method: 'POST' });
                }}
              />
            )}
            {activeCategory === 'processing' && (
              <SettingsProcessingTab formData={formData} setFormData={setFormData} />
            )}
            {activeCategory === 'advanced' && (
              <SettingsAdvancedTab formData={formData} setFormData={setFormData} />
            )}
          </div>

          <div className="bg-[#272727] dark:bg-[var(--bg-surface)] border-t border-white/8 py-3 px-6 flex justify-end items-center gap-3 shrink-0">
            <button
              onClick={onCancel}
              className="px-4 py-1.5 text-[13px] font-medium text-[#A6A6A6] hover:text-[#F3F3F3] hover:bg-white/[0.04] rounded-sm cursor-pointer transition-colors focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
              type="button"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={!isDirty || isSaving}
              className={`min-w-[124px] h-[34px] px-4 rounded-sm text-[13px] font-semibold flex items-center justify-center gap-1.5 transition-colors focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none ${
                saveSuccess
                  ? 'bg-emerald-600 text-white'
                  : isDirty
                    ? 'bg-[#60CDFF] hover:bg-[#4CC2FF] active:bg-[#0091E6] text-[#000000] cursor-pointer'
                    : 'bg-white/10 text-white/40 opacity-40 cursor-not-allowed'
              }`}
              type="button"
            >
              {saveSuccess ? (
                <>
                  <CheckCircle2 className="w-4 h-4" />
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
      </div>
    </div>
  );
};
