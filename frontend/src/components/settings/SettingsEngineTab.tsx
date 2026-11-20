import React, { useRef, useEffect, useState } from 'react';
import { FolderOpen } from 'lucide-react';
import { BackendSettings, DoctorReport, ModelStatusInfo, RuntimeStatusInfo } from '../../types';
import { DoctorDiagnosticSection } from './DoctorDiagnosticSection';
import { ModelWeightsSection } from './ModelWeightsSection';
import { ManagedRuntimeSection } from './ManagedRuntimeSection';

export interface SettingsEngineTabProps {
  formData: BackendSettings;
  setFormData: React.Dispatch<React.SetStateAction<BackendSettings>>;
  effectiveRuntimeStatus: RuntimeStatusInfo | null;
  effectiveModelStatus: ModelStatusInfo | null;
  doctorReport: DoctorReport | null;
  doctorError: string | null;
  isDoctorRunning: boolean;
  isRefreshingHardware: boolean;
  isStartingRuntimeDownload: boolean;
  onRefreshHardware: () => void;
  onRunDoctor: () => void;
  onBrowseExecutable: () => void;
  onDownloadRuntime: () => void;
  onDownloadModel: () => void;
  onCancelModelDownload: () => void;
}

const formatBytes = (bytes: number): string => {
  if (!bytes || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(2)} ${units[i] || 'GB'}`;
};

export const SettingsEngineTab: React.FC<SettingsEngineTabProps> = ({
  formData,
  setFormData,
  effectiveRuntimeStatus,
  effectiveModelStatus,
  doctorReport,
  doctorError,
  isDoctorRunning,
  isRefreshingHardware,
  isStartingRuntimeDownload,
  onRefreshHardware,
  onRunDoctor,
  onBrowseExecutable,
  onDownloadRuntime,
  onDownloadModel,
  onCancelModelDownload,
}) => {
  const [runtimeIndicator, setRuntimeIndicator] = useState<{ left: number; width: number }>({ left: 2, width: 0 });
  const runtimeContainerRef = useRef<HTMLDivElement>(null);
  const runtimeRefs = useRef<{ [key: string]: HTMLButtonElement | null }>({});

  useEffect(() => {
    const currentRuntime = formData.runtime_mode || 'managed';
    if (runtimeContainerRef.current && runtimeRefs.current[currentRuntime]) {
      const cRect = runtimeContainerRef.current.getBoundingClientRect();
      const tRect = runtimeRefs.current[currentRuntime]!.getBoundingClientRect();
      setRuntimeIndicator({ left: tRect.left - cRect.left, width: tRect.width });
    }
  }, [formData.runtime_mode]);

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Local Inference Backend Radios */}
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

      {/* Runtime Binary Source */}
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
              className="absolute top-0.5 bottom-0.5 bg-white dark:bg-[var(--bg-elevated)] rounded-md shadow-xs transition-all duration-200 ease-out"
              style={{ left: `${runtimeIndicator.left}px`, width: `${runtimeIndicator.width}px` }}
            />
            {(['managed', 'custom'] as const).map((mode) => (
              <button
                key={mode}
                ref={(el) => { runtimeRefs.current[mode] = el; }}
                type="button"
                onClick={() => setFormData((prev) => ({ ...prev, runtime_mode: mode }))}
                className={`relative z-10 px-3 py-1 rounded text-[12.5px] font-medium whitespace-nowrap cursor-pointer active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] focus-visible:outline-none ${
                  (formData.runtime_mode || 'managed') === mode 
                    ? 'text-[#14213D] dark:text-[var(--text-1)]' 
                    : 'text-[#5A6478] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)]'
                }`}
              >
                {mode === 'managed' ? 'Managed Local Runtime' : 'Custom Executable Path'}
              </button>
            ))}
          </div>
        </div>

        {formData.runtime_mode === 'managed' || !formData.runtime_mode ? (
          <ManagedRuntimeSection
            formData={formData}
            setFormData={setFormData}
            effectiveRuntimeStatus={effectiveRuntimeStatus}
            doctorReport={doctorReport}
            isRefreshingHardware={isRefreshingHardware}
            isStartingRuntimeDownload={isStartingRuntimeDownload}
            onRefreshHardware={onRefreshHardware}
            onDownloadRuntime={onDownloadRuntime}
            formatBytes={formatBytes}
          />
        ) : (
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
                  onClick={onBrowseExecutable}
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
      <ModelWeightsSection
        effectiveModelStatus={effectiveModelStatus}
        onDownloadModel={onDownloadModel}
        onCancelModelDownload={onCancelModelDownload}
        formatBytes={formatBytes}
      />

      {/* Auto Start Server Toggle */}
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

      {/* Doctor Diagnostic Probe Section */}
      <DoctorDiagnosticSection
        doctorReport={doctorReport}
        doctorError={doctorError}
        isDoctorRunning={isDoctorRunning}
        onRunDoctor={onRunDoctor}
      />
    </div>
  );
};
