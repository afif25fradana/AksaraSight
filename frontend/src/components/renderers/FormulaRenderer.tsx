import React, { useState, useMemo, useRef, useEffect } from 'react';
import katex from 'katex';
import 'katex/dist/katex.min.css';
import { Code, Eye, Check, Copy } from 'lucide-react';

interface FormulaRendererProps {
  latex: string;
  displayMode?: boolean;
  className?: string;
}

export const FormulaRenderer: React.FC<FormulaRendererProps> = ({
  latex,
  displayMode = true,
  className = '',
}) => {
  const [showRaw, setShowRaw] = useState(false);
  const [copied, setCopied] = useState(false);
  const copyTimeoutRef = useRef<any>(null);

  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current) {
        clearTimeout(copyTimeoutRef.current);
      }
    };
  }, []);

  const cleanLatex = useMemo(() => {
    let expr = latex.trim();
    // Strip wrapping $$ or $ delimiters if already present
    if (expr.startsWith('$$') && expr.endsWith('$$')) {
      expr = expr.slice(2, -2).trim();
    } else if (expr.startsWith('$') && expr.endsWith('$') && expr.length > 2) {
      expr = expr.slice(1, -1).trim();
    }
    return expr;
  }, [latex]);

  const renderedHtml = useMemo(() => {
    try {
      return katex.renderToString(cleanLatex, {
        displayMode,
        throwOnError: false,
        strict: false,
        trust: false,
        output: 'htmlAndMathml',
      });
    } catch {
      return null;
    }
  }, [cleanLatex, displayMode]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(cleanLatex);
      setCopied(true);
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
      copyTimeoutRef.current = setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.warn('Failed to copy LaTeX:', err);
    }
  };

  return (
    <div
      className={`my-2 p-3 rounded-lg bg-[#0F766E]/5 dark:bg-[var(--accent)]/10 border border-[#0F766E]/20 dark:border-[var(--accent)]/30 font-sans text-[13px] text-[#14213D] dark:text-[var(--text-1)] relative group ${className}`}
    >
      <div className="flex items-center justify-between gap-2 mb-2 pb-1.5 border-b border-[#0F766E]/15 dark:border-[var(--accent)]/20 text-2xs uppercase tracking-wider font-semibold text-[#0F766E] dark:text-[var(--accent)] select-none">
        <span>Mathematical Formula</span>

        <div className="flex items-center gap-1 normal-case tracking-normal">
          <button
            type="button"
            onClick={handleCopy}
            className="h-6 px-2 rounded hover:bg-black/5 dark:hover:bg-white/5 text-[#5A6478] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)] flex items-center gap-1 text-[11px] transition-colors cursor-pointer"
            title="Copy LaTeX source"
          >
            {copied ? (
              <>
                <Check className="w-3 h-3 text-emerald-600 dark:text-[var(--success)]" aria-hidden="true" />
                <span className="text-emerald-700 dark:text-[var(--success)] font-medium">Copied</span>
              </>
            ) : (
              <>
                <Copy className="w-3 h-3" aria-hidden="true" />
                <span>Copy</span>
              </>
            )}
          </button>

          <button
            type="button"
            onClick={() => setShowRaw(!showRaw)}
            className="h-6 px-2 rounded hover:bg-black/5 dark:hover:bg-white/5 text-[#5A6478] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)] flex items-center gap-1 text-[11px] transition-colors cursor-pointer"
            title={showRaw ? 'Render Math' : 'View LaTeX Source'}
          >
            {showRaw ? (
              <>
                <Eye className="w-3 h-3" aria-hidden="true" />
                <span>View Rendered</span>
              </>
            ) : (
              <>
                <Code className="w-3 h-3" aria-hidden="true" />
                <span>LaTeX Source</span>
              </>
            )}
          </button>
        </div>
      </div>

      {showRaw || !renderedHtml ? (
        <pre className="p-2 rounded bg-black/[0.03] dark:bg-[var(--bg-base)] text-[#0F766E] dark:text-[var(--accent)] font-mono text-xs overflow-x-auto whitespace-pre-wrap select-text">
          {cleanLatex}
        </pre>
      ) : (
        <div
          className="overflow-x-auto py-1 select-text"
          dangerouslySetInnerHTML={{ __html: renderedHtml }}
        />
      )}
    </div>
  );
};
