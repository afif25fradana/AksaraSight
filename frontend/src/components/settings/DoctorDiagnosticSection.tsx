import React from 'react';
import { RefreshCw, Stethoscope } from 'lucide-react';
import { DoctorReport } from '../../types';

export interface DoctorDiagnosticSectionProps {
  doctorReport: DoctorReport | null;
  doctorError: string | null;
  isDoctorRunning: boolean;
  onRunDoctor: () => void;
}

export const DoctorDiagnosticSection: React.FC<DoctorDiagnosticSectionProps> = ({
  doctorReport,
  doctorError,
  isDoctorRunning,
  onRunDoctor,
}) => {
  return (
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
          onClick={onRunDoctor}
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
  );
};
