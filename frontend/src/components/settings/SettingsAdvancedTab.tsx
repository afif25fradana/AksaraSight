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

      {/* Security Confirmation Warning Modal Dialog */}
      {showSecurityWarning && (
        <div 
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#14213D]/40 dark:bg-black/70 backdrop-blur-[4px] animate-modal-backdrop"
          onClick={() => setShowSecurityWarning(false)}
        >
          <div 
            ref={securityModalRef}
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
