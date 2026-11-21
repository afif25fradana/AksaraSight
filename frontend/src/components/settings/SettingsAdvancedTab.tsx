import React, { useState, useEffect } from 'react';
import { AlertTriangle } from 'lucide-react';
import { BackendSettings } from '../../types';
import { useFocusTrap } from '../../hooks/useFocusTrap';

export interface SettingsAdvancedTabProps {
  formData: BackendSettings;
  setFormData: React.Dispatch<React.SetStateAction<BackendSettings>>;
}

export const SettingsAdvancedTab: React.FC<SettingsAdvancedTabProps> = ({
  formData,
  setFormData,
}) => {
  const [showSecurityWarning, setShowSecurityWarning] = useState(false);
  const securityModalRef = useFocusTrap<HTMLDivElement>(showSecurityWarning);

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

  return (
    <div className="space-y-4 animate-fade-in">
      <div className="bg-[#2D2D2D] p-4 rounded-lg border border-white/[0.04] space-y-3.5 transition-colors">
        {/* Local Engine HTTP Endpoint URL */}
        <div>
          <label className="block text-[13px] font-medium text-[#F3F3F3] mb-1" htmlFor="endpoint">
            Local Engine HTTP Endpoint URL
          </label>
          <input 
            id="endpoint" 
            type="text" 
            value={formData.local_endpoint}
            onChange={(e) => setFormData((prev) => ({ ...prev, local_endpoint: e.target.value }))}
            className="w-full h-[34px] px-3 font-mono text-[12.5px] bg-[#202020] border border-white/[0.06] rounded-md text-[#F3F3F3] focus:outline-none focus:border-[#60CDFF] focus:ring-1 focus:ring-[#60CDFF]" 
          />
        </div>

        {/* Allow Remote Endpoints */}
        <div className="flex items-center justify-between pt-2 border-t border-white/[0.04]">
          <div>
            <span className="text-[13px] font-semibold text-[#F3F3F3] block">
              Allow Non-Loopback (Remote) Endpoints
            </span>
            <p className="text-[12px] text-[#A6A6A6] mt-0.5">
              Permit connections outside 127.0.0.1 or localhost (violates 100% local guarantee)
            </p>
          </div>
          <button 
            role="switch" 
            aria-checked={formData.allow_remote || false}
            aria-label="Allow Non-Loopback (Remote) Endpoints"
            onClick={handleToggleRemote}
            className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:ring-offset-2 focus-visible:ring-offset-[#202020] ${
              formData.allow_remote ? 'bg-[#60CDFF]' : 'bg-white/20'
            }`} 
            type="button" 
          >
            <span 
              className={`pointer-events-none inline-block h-5 w-5 transform rounded-full shadow-xs ring-0 transition duration-200 ease-in-out ${
                formData.allow_remote ? 'translate-x-5 bg-[#000000]' : 'translate-x-0 bg-white'
              }`} 
            />
          </button>
        </div>

        {/* Mutable Network Limits: Timeout and Max Retries */}
        <div className="grid grid-cols-2 gap-4 pt-2 border-t border-white/[0.04]">
          <div>
            <label className="block text-[13px] font-medium text-[#F3F3F3] mb-1" htmlFor="req-timeout">
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
                className="w-full max-w-[100px] h-[34px] px-2.5 text-[13.5px] bg-[#202020] border border-white/[0.06] rounded-md text-[#F3F3F3] focus:outline-none focus:border-[#60CDFF] focus:ring-1 focus:ring-[#60CDFF]" 
              />
              <span className="text-[12px] text-[#A6A6A6]">s</span>
            </div>
          </div>

          <div>
            <label className="block text-[13px] font-medium text-[#F3F3F3] mb-1" htmlFor="retries">
              Max Retry Attempts
            </label>
            <input 
              id="retries" 
              type="number" 
              min={0}
              max={10}
              value={formData.max_retries}
              onChange={(e) => setFormData((prev) => ({ ...prev, max_retries: Number(e.target.value) }))}
              className="w-full max-w-[100px] h-[34px] px-2.5 text-[13.5px] bg-[#202020] border border-white/[0.06] rounded-md text-[#F3F3F3] focus:outline-none focus:border-[#60CDFF] focus:ring-1 focus:ring-[#60CDFF]" 
            />
          </div>
        </div>

        {/* Hugging Face Model Repository */}
        <div className="pt-2 border-t border-white/[0.04]">
          <label className="block text-[13px] font-medium text-[#F3F3F3] mb-1" htmlFor="model-repo">
            Hugging Face Model Repository
          </label>
          <input 
            id="model-repo" 
            type="text" 
            value={formData.model_repo}
            onChange={(e) => setFormData((prev) => ({ ...prev, model_repo: e.target.value }))}
            className="w-full h-[34px] px-3 font-mono text-[12.5px] bg-[#202020] border border-white/[0.06] rounded-md text-[#F3F3F3] focus:outline-none focus:border-[#60CDFF] focus:ring-1 focus:ring-[#60CDFF]" 
          />
        </div>
      </div>

      {/* Security Confirmation Warning Modal Dialog */}
      {showSecurityWarning && (
        <div 
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-[4px] animate-modal-backdrop"
          onClick={() => setShowSecurityWarning(false)}
        >
          <div 
            ref={securityModalRef}
            className="w-full max-w-md bg-[#272727] rounded-lg shadow-xs border border-white/[0.08] p-5 space-y-4 text-[#F3F3F3] animate-modal-window will-change-transform transition-colors"
            onClick={(e) => e.stopPropagation()}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="security-warning-title"
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-md bg-red-500/15 flex items-center justify-center text-[#e58383] shrink-0">
                <AlertTriangle className="w-5 h-5 text-[#e58383]" aria-hidden="true" />
              </div>
              <div>
                <h3 id="security-warning-title" className="font-semibold text-[15px] text-[#F3F3F3]">
                  Security Notice: Remote Endpoint
                </h3>
                <span className="text-[12px] text-[#e58383] font-medium">
                  Violates 100% Local Guarantee
                </span>
              </div>
            </div>

            <p className="text-[13px] text-[#A6A6A6] leading-relaxed">
              Connecting to an external endpoint transmits document images outside this machine. AksaraSight is architected for strict offline-first archival confidentiality.
            </p>

            <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-white/[0.04]">
              <button
                type="button"
                onClick={() => setShowSecurityWarning(false)}
                className="px-3.5 py-1.5 text-[12.5px] border border-white/[0.08] hover:border-white/[0.16] bg-[#2D2D2D] text-[#F3F3F3] rounded-md font-medium cursor-pointer active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  setFormData((prev) => ({ ...prev, allow_remote: true }));
                  setShowSecurityWarning(false);
                }}
                className="px-4 py-1.5 text-[12.5px] bg-[#e58383] hover:bg-[#d97070] text-[#000000] rounded-md font-semibold cursor-pointer shadow-xs active:scale-[0.96] active:translate-y-px active:brightness-95 transition-all duration-150 ease-out focus-visible:ring-2 focus-visible:ring-[#e58383] focus-visible:outline-none"
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
