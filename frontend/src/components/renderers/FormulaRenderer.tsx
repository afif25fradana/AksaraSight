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
      className={`my-2 p-3 rounded-lg bg-[#272727] border border-white/[0.04] font-sans text-[13px] text-[#F3F3F3] relative group ${className}`}
    >
      <div className="flex items-center justify-between gap-2 mb-2 pb-1.5 border-b border-white/[0.04] text-2xs uppercase tracking-wider font-semibold text-[#60CDFF] select-none">
        <span>Mathematical Formula</span>

        <div className="flex items-center gap-1 normal-case tracking-normal">
          <button
            type="button"
            onClick={handleCopy}
            className="h-6 px-2 rounded-md hover:bg-white/5 text-[#A6A6A6] hover:text-[#F3F3F3] flex items-center gap-1 text-[11px] transition-colors cursor-pointer"
            title="Copy LaTeX source"
          >
            {copied ? (
              <>
                <Check className="w-3 h-3 text-[#78c697]" aria-hidden="true" />
                <span className="text-[#78c697] font-medium">Copied</span>
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
            className="h-6 px-2 rounded-md hover:bg-white/5 text-[#A6A6A6] hover:text-[#F3F3F3] flex items-center gap-1 text-[11px] transition-colors cursor-pointer"
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
        <pre className="p-2 rounded-md bg-[#202020] text-[#60CDFF] font-mono text-xs overflow-x-auto whitespace-pre-wrap select-text border border-white/[0.04]">
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
