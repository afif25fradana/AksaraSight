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
      <div className="space-y-2.5">
        <label className="block text-[13.5px] font-semibold text-[#F3F3F3]">
          Local Inference Engine Backend
        </label>
        <div className="grid grid-cols-3 gap-3">
          {(['llama-cpp', 'ollama', 'vllm'] as const).map((backendOption) => {
            const isSelected = formData.backend === backendOption;
            return (
              <label 
                key={backendOption}
                className={`flex items-center gap-2.5 px-3.5 py-2.5 rounded-lg border cursor-pointer transition-all duration-150 active:scale-[0.98] ${
                  isSelected 
                    ? 'border-[#60CDFF] bg-[#60CDFF]/10 ring-1 ring-[#60CDFF]/30 shadow-xs' 
                    : 'bg-[#272727] border-white/[0.08] hover:border-white/[0.16] hover:bg-[#2d2d2d]'
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
                      ? 'border-[#60CDFF] bg-[#272727]' 
                      : 'border-white/[0.15] bg-transparent'
                  }`}
                  aria-hidden="true"
                >
                  <div 
                    className={`w-2 h-2 rounded-full bg-[#60CDFF] transition-transform duration-150 ease-out ${
                      isSelected ? 'scale-100 opacity-100' : 'scale-0 opacity-0'
                    }`} 
                  />
                </div>
                <span className={`text-[13.5px] ${isSelected ? 'font-medium text-[#F3F3F3]' : 'text-[#A6A6A6]'}`}>
                  {backendOption}
                </span>
              </label>
            );
          })}
        </div>
      </div>

      {/* Runtime Binary Source */}
      <div className="bg-[#272727] p-4 rounded-lg border border-white/[0.06] space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <label className="text-[13.5px] font-semibold text-[#F3F3F3] block">
              Runtime Binary Source
            </label>
            <p className="text-[12px] text-[#A6A6A6] mt-0.5">
              Choose between AksaraSight-managed precompiled binary or a custom llama-server binary
            </p>
          </div>
          <div 
            ref={runtimeContainerRef}
            className="relative inline-flex p-0.5 bg-black/20 border border-white/[0.06] rounded-md gap-1 whitespace-nowrap"
          >
            <div 
              className="absolute top-0.5 bottom-0.5 bg-[#383838] rounded shadow-xs transition-all duration-200 ease-out"
              style={{ left: `${runtimeIndicator.left}px`, width: `${runtimeIndicator.width}px` }}
            />
            {(['managed', 'custom'] as const).map((mode) => (
              <button
                key={mode}
                ref={(el) => { runtimeRefs.current[mode] = el; }}
                type="button"
                onClick={() => setFormData((prev) => ({ ...prev, runtime_mode: mode }))}
                className={`relative z-10 px-3 py-1 rounded text-[12.5px] font-medium whitespace-nowrap cursor-pointer active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none ${
                  (formData.runtime_mode || 'managed') === mode 
                    ? 'text-[#F3F3F3]' 
                    : 'text-[#A6A6A6] hover:text-[#F3F3F3]'
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
          <div className="pt-3 border-t border-white/[0.04] space-y-3 transition-colors animate-fade-in">
            <div>
              <label className="block text-[13px] font-medium text-[#F3F3F3] mb-1.5" htmlFor="custom-server-path">
                Custom llama-server Executable Path
              </label>
              <div className="flex items-center gap-2">
                <input
                  id="custom-server-path"
                  type="text"
                  value={formData.llama_server_path || ''}
                  onChange={(e) => setFormData((prev) => ({ ...prev, llama_server_path: e.target.value }))}
                  placeholder="C:\tools\llama-cpp\llama-server.exe"
                  className="flex-1 h-[34px] px-3 font-mono text-[12px] bg-white/[0.03] border border-white/[0.06] rounded-md text-[#F3F3F3] focus:outline-none focus:border-[#60CDFF] focus:ring-1 focus:ring-[#60CDFF]"
                />
                <button
                  type="button"
                  onClick={onBrowseExecutable}
                  className="h-[34px] px-3 border border-white/[0.08] hover:border-white/[0.16] bg-white/[0.04] hover:bg-white/[0.08] text-[#F3F3F3] rounded-md text-[12.5px] font-medium active:scale-[0.98] transition-transform duration-100 cursor-pointer flex items-center gap-1 focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
                  title="Browse local disk for llama-server executable"
                >
                  <FolderOpen className="w-3.5 h-3.5 text-[#60CDFF]" />
                  <span>Browse...</span>
                </button>
              </div>
              {formData.llama_server_path ? (
                <p className="text-[11.5px] text-[#A6A6A6] mt-1.5 flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-[#78c697]" />
                  <span>Custom llama-server binary configured</span>
                </p>
              ) : (
                <p className="text-[11.5px] text-[#A6A6A6] mt-1.5">
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
      <div className="flex items-center justify-between bg-[#272727] p-4 rounded-lg border border-white/[0.06] transition-colors">
        <div>
          <span className="text-[13.5px] font-semibold text-[#F3F3F3] block">
            Start engine automatically with Web UI
          </span>
          <p className="text-[12px] text-[#A6A6A6] mt-0.5">
            Spawn background llama-server process on workspace startup
          </p>
        </div>
        <button 
          role="switch" 
          aria-checked={formData.auto_start_server}
          aria-label="Start engine automatically with Web UI"
          onClick={() => setFormData((prev) => ({ ...prev, auto_start_server: !prev.auto_start_server }))}
          className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:ring-offset-2 focus-visible:ring-offset-[#202020] ${
            formData.auto_start_server ? 'bg-[#60CDFF]' : 'bg-white/20'
          }`} 
          type="button" 
        >
          <span 
            className={`pointer-events-none inline-block h-5 w-5 transform rounded-full shadow-xs ring-0 transition duration-200 ease-in-out ${
              formData.auto_start_server ? 'translate-x-5 bg-[#000000]' : 'translate-x-0 bg-white'
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
