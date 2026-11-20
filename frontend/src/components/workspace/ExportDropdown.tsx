import React, { useRef, useEffect } from 'react';
import { Download, ChevronDown, Check } from 'lucide-react';
import { OutputFormatType } from '../../types';

export interface ExportDropdownProps {
  isOpen: boolean;
  onToggleOpen: () => void;
  onClose: () => void;
  onExport: (format: OutputFormatType) => void;
  selectedFormat: OutputFormatType;
  onSelectFormat: (format: OutputFormatType) => void;
}

export const EXPORT_FORMATS: { ext: OutputFormatType; title: string; desc: string }[] = [
  { ext: 'docx', title: 'DOCX (.docx)', desc: 'Microsoft Word document' },
  { ext: 'md', title: 'Markdown (.md)', desc: 'Markdown text & tables' },
  { ext: 'json', title: 'JSON (.json)', desc: 'Structured metadata, timing & page tokens' },
  { ext: 'both', title: 'Both (.md + .json)', desc: 'Markdown document and JSON side-by-side' },
];

export const ExportDropdown: React.FC<ExportDropdownProps> = ({
  isOpen,
  onToggleOpen,
  onClose,
  onExport,
  selectedFormat,
  onSelectFormat,
}) => {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };

    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('mousedown', handleClickOutside);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen, onClose]);

  return (
    <div ref={menuRef} className="relative inline-flex">
      <button
        onClick={onToggleOpen}
        className="h-8 px-3 bg-[#0F766E] hover:bg-[#115E59] active:bg-[#0d4f4b] text-white font-semibold text-xs rounded-lg shadow-xs active:scale-[0.96] active:translate-y-px active:brightness-95 transition-all duration-150 ease-out flex items-center gap-1.5 cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none"
        type="button"
        aria-haspopup="true"
        aria-expanded={isOpen}
      >
        <Download className="w-4 h-4 text-white" aria-hidden="true" />
        <span>Export</span>
        <ChevronDown className="w-3.5 h-3.5 text-white/80" aria-hidden="true" />
      </button>

      {isOpen && (
        <div
          className="absolute right-0 top-9 w-60 bg-white dark:bg-[var(--bg-elevated)] rounded-lg border border-[#8A94A6]/30 dark:border-[var(--border)] py-1.5 z-30 shadow-lg text-[13px] origin-top-right animate-dropdown"
          role="menu"
          aria-label="Export format options"
        >
          <div className="px-3 py-1 text-2xs font-semibold uppercase tracking-wider text-[#5A6478] dark:text-[var(--text-2)] border-b border-black/5 dark:border-[var(--border)] mb-1">
            Engine Output Format
          </div>
          {EXPORT_FORMATS.map((fmt) => (
            <button
              key={fmt.ext}
              onClick={() => {
                onSelectFormat(fmt.ext);
                onExport(fmt.ext);
                onClose();
              }}
              className={`w-full text-left px-3 py-1.5 hover:bg-black/5 hover:dark:bg-[var(--bg-active)] flex items-center justify-between cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none ${
                selectedFormat === fmt.ext ? 'bg-black/[0.04] dark:bg-[var(--bg-active)]' : ''
              }`}
              type="button"
              role="menuitem"
            >
              <div>
                <span className="font-semibold text-[#14213D] dark:text-[var(--text-1)] block text-xs">
                  {fmt.title}
                </span>
                <span className="text-2xs text-[#4B5563] dark:text-[var(--text-2)] block">
                  {fmt.desc}
                </span>
              </div>
              {selectedFormat === fmt.ext && (
                <Check className="w-4 h-4 text-[#0F766E] dark:text-[var(--accent)] ml-2 shrink-0" aria-hidden="true" />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
