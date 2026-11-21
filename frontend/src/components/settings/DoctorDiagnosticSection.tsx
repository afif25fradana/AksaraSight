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
    <div className="bg-[#2D2D2D] p-4 rounded-lg border border-white/[0.04] space-y-3 transition-colors">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-[13.5px] font-semibold text-[#F3F3F3] flex items-center gap-1.5">
            <Stethoscope className="w-4 h-4 text-[#60CDFF]" />
            <span>System Diagnostic Probe</span>
          </span>
          <p className="text-[12px] text-[#A6A6A6] mt-0.5">
            Test hardware, runtime, backend reachability, and vision inference
          </p>
        </div>
        <button
          type="button"
          onClick={onRunDoctor}
          disabled={isDoctorRunning}
          className="inline-flex items-center gap-1.5 h-8 px-3.5 bg-[#60CDFF] hover:bg-[#4CC2FF] active:bg-[#0091E6] text-[#000000] rounded-md text-[12px] font-semibold active:scale-[0.96] transition-all duration-150 cursor-pointer shadow-xs disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isDoctorRunning ? 'animate-spin' : ''}`} />
          <span>{isDoctorRunning ? 'Probing...' : 'Run Doctor'}</span>
        </button>
      </div>

      {doctorError && (
        <div role="alert" className="p-2.5 bg-red-500/10 border border-red-500/30 text-[#e58383] rounded-md text-xs">
          {doctorError}
        </div>
      )}

      {doctorReport && (
        <div className="p-3.5 bg-[#202020] border border-white/[0.04] text-[#F3F3F3] shadow-xs rounded-lg font-mono text-[11.5px] leading-relaxed animate-fade-in space-y-2.5">
          <div className="flex items-center justify-between border-b border-white/[0.04] pb-2 font-sans">
            <span className="text-[#F3F3F3] font-semibold text-[12.5px]">
              Diagnostic Verification Report
            </span>
            <span className={`font-mono text-[11px] px-2 py-0.5 rounded-sm font-semibold border ${
              doctorReport.failed_checks === 0
                ? 'bg-[#78c697]/15 text-[#78c697] border-[#78c697]/30'
                : 'bg-red-500/15 text-[#e58383] border-red-500/30'
            }`}>
              {doctorReport.status} ({doctorReport.total_checks - doctorReport.failed_checks}/{doctorReport.total_checks} PASS)
            </span>
          </div>
          <div className="space-y-2">
            {doctorReport.checks?.map((res, idx) => (
              <div key={idx} className="border-b border-white/[0.04] last:border-b-0 pb-2 pt-0.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <span className={`font-bold font-mono ${
                      res.status === 'PASS' 
                        ? 'text-[#78c697]' 
                        : res.status === 'WARN' 
                          ? 'text-[#e0a96d]' 
                          : 'text-[#e58383]'
                    }`}>
                      [{res.status}]
                    </span>
                    <span className="text-[#F3F3F3] font-semibold">
                      {res.title || res.category}
                    </span>
                  </div>
                  {res.category && res.title && res.title !== res.category && (
                    <span className="text-2xs text-[#A6A6A6] font-sans">
                      {res.category}
                    </span>
                  )}
                </div>

                {res.details && (
                  <div className="pl-6 pt-1 text-[#A6A6A6] font-mono text-[11.5px] space-y-0.5">
                    {Array.isArray(res.details) ? (
                      res.details.map((d, dIdx) => <div key={dIdx}>{d}</div>)
                    ) : (
                      <div>{res.details}</div>
                    )}
                  </div>
                )}

                {res.remediation && (
                  <div className="pl-6 pt-1 text-[#e0a96d] font-sans text-[11px] flex items-center gap-1">
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
