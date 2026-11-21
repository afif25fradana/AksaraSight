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
        className="h-8 px-3 bg-[#60CDFF] hover:bg-[#4CC2FF] active:bg-[#0091E6] text-[#000000] font-semibold text-[13px] rounded-sm shadow-xs active:scale-[0.98] transition-all duration-100 ease-out flex items-center gap-1.5 cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
        type="button"
        aria-haspopup="true"
        aria-expanded={isOpen}
      >
        <Download className="w-4 h-4 text-[#000000]" aria-hidden="true" />
        <span>Export</span>
        <ChevronDown className="w-3.5 h-3.5 text-[#000000]/80" aria-hidden="true" />
      </button>

      {isOpen && (
        <div
          className="absolute right-0 top-9 w-60 bg-[#272727] dark:bg-[var(--bg-elevated)] rounded-sm border border-white/10 shadow-[0_8px_16px_rgba(0,0,0,0.36)] py-1.5 z-30 text-[13px] origin-top-right animate-dropdown"
          role="menu"
          aria-label="Export format options"
        >
          <div className="px-3 py-1 text-2xs font-semibold uppercase tracking-wider text-[#A6A6A6] border-b border-white/8 mb-1">
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
              className={`w-full text-left px-3 py-1.5 hover:bg-white/[0.08] flex items-center justify-between cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none transition-colors ${
                selectedFormat === fmt.ext ? 'bg-white/[0.05]' : ''
              }`}
              type="button"
              role="menuitem"
            >
              <div>
                <span className="font-semibold text-[#F3F3F3] block text-xs">
                  {fmt.title}
                </span>
                <span className="text-2xs text-[#A6A6A6] block">
                  {fmt.desc}
                </span>
              </div>
              {selectedFormat === fmt.ext && (
                <Check className="w-4 h-4 text-[#60CDFF] ml-2 shrink-0" aria-hidden="true" />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
