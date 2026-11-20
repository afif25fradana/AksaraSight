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
            className={`pointer-events-auto flex items-start gap-3 p-3.5 rounded-lg border shadow-lg text-[13px] leading-snug transition-all duration-200 animate-fade-in ${
              item.type === 'error'
                ? 'bg-[#FEF2F2] dark:bg-[var(--bg-elevated)] border-red-300 dark:border-[var(--danger)]/50 text-[#991B1B] dark:text-[var(--danger)]'
                : item.type === 'warning'
                ? 'bg-amber-50 dark:bg-[var(--bg-elevated)] border-amber-300 dark:border-[var(--warning)]/50 text-amber-900 dark:text-[var(--warning)]'
                : item.type === 'success'
                ? 'bg-emerald-50 dark:bg-[var(--bg-elevated)] border-emerald-300 dark:border-[var(--success)]/50 text-emerald-900 dark:text-[var(--success)]'
                : 'bg-white dark:bg-[var(--bg-elevated)] border-[#8A94A6]/30 dark:border-[var(--border)] text-[#14213D] dark:text-[var(--text-1)]'
            }`}
          >
            <div className="shrink-0 mt-0.5">
              {item.type === 'error' ? (
                <AlertCircle className="w-4 h-4 text-red-600 dark:text-[var(--danger)]" aria-hidden="true" />
              ) : item.type === 'warning' ? (
                <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-[var(--warning)]" aria-hidden="true" />
              ) : item.type === 'success' ? (
                <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-[var(--success)]" aria-hidden="true" />
              ) : (
                <Info className="w-4 h-4 text-[#0F766E] dark:text-[var(--accent)]" aria-hidden="true" />
              )}
            </div>

            <div className="flex-1 min-w-0 pr-1 break-words font-medium">
              {item.message}
            </div>

            <button
              type="button"
              onClick={() => removeToast(item.id)}
              className="shrink-0 w-6 h-6 -mr-1 -mt-1 rounded flex items-center justify-center text-[#5A6478] dark:text-[var(--text-2)] hover:text-[#14213D] hover:dark:text-[var(--text-1)] hover:bg-black/5 dark:hover:bg-white/5 transition-colors cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none"
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
