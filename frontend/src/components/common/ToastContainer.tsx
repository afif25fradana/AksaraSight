import React from 'react';
import { useToast } from '../../hooks/useToast';
import { AlertCircle, AlertTriangle, CheckCircle2, Info, X } from 'lucide-react';

export const ToastContainer: React.FC = () => {
  const { toasts, removeToast } = useToast();

  if (toasts.length === 0) return null;

  return (
    <div
      role="region"
      aria-label="Notifications"
      className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none px-4 sm:px-0"
    >
      {toasts.map((item) => {
        const isAssertive = item.type === 'error' || item.type === 'warning';
        return (
          <div
            key={item.id}
            role={isAssertive ? 'alert' : 'status'}
            aria-live={isAssertive ? 'assertive' : 'polite'}
            className={`pointer-events-auto flex items-start gap-3 p-3.5 rounded-lg border shadow-xs text-[13px] leading-snug transition-all duration-200 animate-fade-in ${
              item.type === 'error'
                ? 'bg-[#2D2D2D] border-red-500/40 text-[#e58383]'
                : item.type === 'warning'
                ? 'bg-[#2D2D2D] border-amber-500/40 text-[#e0a96d]'
                : item.type === 'success'
                ? 'bg-[#2D2D2D] border-[#78c697]/40 text-[#78c697]'
                : 'bg-[#2D2D2D] border-white/[0.08] text-[#F3F3F3]'
            }`}
          >
            <div className="shrink-0 mt-0.5">
              {item.type === 'error' ? (
                <AlertCircle className="w-4 h-4 text-[#e58383]" aria-hidden="true" />
              ) : item.type === 'warning' ? (
                <AlertTriangle className="w-4 h-4 text-[#e0a96d]" aria-hidden="true" />
              ) : item.type === 'success' ? (
                <CheckCircle2 className="w-4 h-4 text-[#78c697]" aria-hidden="true" />
              ) : (
                <Info className="w-4 h-4 text-[#60CDFF]" aria-hidden="true" />
              )}
            </div>

            <div className="flex-1 min-w-0 pr-1 break-words font-medium">
              {item.message}
            </div>

            <button
              type="button"
              onClick={() => removeToast(item.id)}
              className="shrink-0 w-6 h-6 -mr-1 -mt-1 rounded flex items-center justify-center text-[#A6A6A6] hover:text-[#F3F3F3] hover:bg-white/5 transition-colors cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
              aria-label="Dismiss notification"
            >
              <X className="w-3.5 h-3.5" aria-hidden="true" />
            </button>
          </div>
        );
      })}
    </div>
  );
};
