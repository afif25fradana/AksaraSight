import React, { useRef, useEffect } from 'react';
import { SlidersHorizontal, ChevronDown, Check } from 'lucide-react';
import { PromptMode } from '../../types';

export interface ExtractionOptionsPopoverProps {
  taskMode: PromptMode;
  currentDpi: number;
  onSelectMode: (mode: PromptMode) => void;
  onSelectDpi: (dpi: number) => void;
  isOpen: boolean;
  onToggleOpen: () => void;
  onClose: () => void;
}

export const TARGET_MODES: { mode: PromptMode; label: string; shortLabel: string; desc: string }[] = [
  {
    mode: 'text',
    label: 'Full Document (Text & Tables)',
    shortLabel: 'Full Document',
    desc: 'Transcribes entire page; formats tables into Markdown',
  },
  {
    mode: 'table',
    label: 'Single Table Crop (Table Only)',
    shortLabel: 'Single Table Crop',
    desc: 'For cropped table images only (omits surrounding text)',
  },
  {
    mode: 'formula',
    label: 'Math & Formulas',
    shortLabel: 'Math & Formulas',
    desc: 'Transcribes equations into LaTeX',
  },
];

export const RESOLUTION_OPTIONS: { dpi: number; label: string; desc: string; recommended?: boolean }[] = [
  {
    dpi: 100,
    label: 'Standard (100 DPI)',
    desc: 'Fast & low memory; best for typed letters & memos',
    recommended: false,
  },
  {
    dpi: 150,
    label: 'High Detail (150 DPI)',
    desc: 'Sharpest for dense forms, grid tables & small fonts',
    recommended: true,
  },
  {
    dpi: 200,
    label: 'Ultra Sharp (200 DPI)',
    desc: 'Maximum detail for blurry scans or camera captures',
    recommended: false,
  },
];

export const ExtractionOptionsPopover: React.FC<ExtractionOptionsPopoverProps> = ({
  taskMode,
  currentDpi,
  onSelectMode,
  onSelectDpi,
  isOpen,
  onToggleOpen,
  onClose,
}) => {
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };

    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
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

  const activeMode = TARGET_MODES.find((m) => m.mode === taskMode);

  return (
    <div className="relative inline-flex items-center" ref={popoverRef}>
      <button
        type="button"
        onClick={onToggleOpen}
        className="h-8 px-2.5 bg-white/[0.04] hover:bg-white/[0.08] text-[#F3F3F3] rounded-sm text-xs font-medium flex items-center gap-1.5 border border-white/8 active:scale-[0.98] transition-all duration-100 ease-out cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
        title="Extraction Options (Target Mode & Scan Detail)"
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        aria-label="Extraction Options"
      >
        <SlidersHorizontal className="w-3.5 h-3.5 text-[#60CDFF]" aria-hidden="true" />
        <span className="font-semibold">{activeMode?.shortLabel || 'Full Document'}</span>
        <span className="text-2xs font-mono px-1.5 py-0.5 rounded-sm bg-white/5 text-[#A6A6A6] border border-white/8">
          {currentDpi} DPI
        </span>
        <ChevronDown className="w-3 h-3 text-[#A6A6A6]" aria-hidden="true" />
      </button>

      {isOpen && (
        <div
          className="absolute left-0 top-9 w-[290px] bg-[#272727] dark:bg-[var(--bg-elevated)] rounded-sm border border-white/10 shadow-[0_8px_16px_rgba(0,0,0,0.36)] py-1.5 z-30 text-[13px] origin-top-left animate-dropdown"
          role="dialog"
          aria-label="Extraction Options"
        >
          {/* Section 1: EXTRACTION TARGET */}
          <div className="px-3 py-1 text-2xs font-semibold uppercase tracking-wider text-[#A6A6A6] border-b border-white/8 mb-1">
            EXTRACTION TARGET
          </div>
          <div role="group" aria-label="Extraction target modes">
            {TARGET_MODES.map((tm) => (
              <button
                key={tm.mode}
                type="button"
                onClick={() => {
                  onSelectMode(tm.mode);
                }}
                className={`w-full text-left px-3 py-1.5 hover:bg-white/[0.08] flex items-center justify-between cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none transition-colors ${
                  taskMode === tm.mode ? 'bg-[#60CDFF]/15' : ''
                }`}
                role="menuitem"
              >
                <div className="pr-2">
                  <span className="font-semibold text-[#F3F3F3] block text-xs">
                    {tm.label}
                  </span>
                  <span className="text-2xs text-[#A6A6A6] block leading-snug">
                    {tm.desc}
                  </span>
                </div>
                {taskMode === tm.mode && (
                  <Check className="w-4 h-4 text-[#60CDFF] ml-2 shrink-0" aria-hidden="true" />
                )}
              </button>
            ))}
          </div>

          {/* Section 2: SCAN DETAIL / RESOLUTION */}
          <div className="px-3 pt-2 pb-1 flex items-center justify-between text-2xs font-semibold uppercase tracking-wider text-[#A6A6A6] border-t border-b border-white/8 my-1">
            <span>SCAN DETAIL / RESOLUTION</span>
            <span className="font-normal normal-case text-[10px] text-[#60CDFF] font-mono">
              Syncs with Settings
            </span>
          </div>
          <div role="group" aria-label="Scan detail resolution options">
            {RESOLUTION_OPTIONS.map((res) => (
              <button
                key={res.dpi}
                type="button"
                onClick={() => {
                  onSelectDpi(res.dpi);
                }}
                className={`w-full text-left px-3 py-1.5 hover:bg-white/[0.08] flex items-center justify-between cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none transition-colors ${
                  currentDpi === res.dpi ? 'bg-[#60CDFF]/15' : ''
                }`}
                role="menuitem"
              >
                <div className="pr-2">
                  <div className="flex items-center gap-1.5">
                    <span className="font-semibold text-[#F3F3F3] block text-xs">
                      {res.label}
                    </span>
                    {res.recommended && (
                      <span className="text-2xs font-semibold uppercase px-1.5 py-0.5 rounded-sm bg-[#60CDFF]/20 text-[#60CDFF]">
                        Recommended
                      </span>
                    )}
                  </div>
                  <span className="text-2xs text-[#A6A6A6] block leading-snug">
                    {res.desc}
                  </span>
                </div>
                {currentDpi === res.dpi && (
                  <Check className="w-4 h-4 text-[#60CDFF] ml-2 shrink-0" aria-hidden="true" />
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
