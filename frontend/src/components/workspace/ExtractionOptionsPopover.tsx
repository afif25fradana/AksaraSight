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
  const triggerButtonRef = useRef<HTMLButtonElement>(null);
  const targetModeRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const resolutionRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    if (isOpen) {
      const activeIdx = TARGET_MODES.findIndex((t) => t.mode === taskMode);
      const targetIdx = activeIdx >= 0 ? activeIdx : 0;
      requestAnimationFrame(() => {
        targetModeRefs.current[targetIdx]?.focus();
      });
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
        triggerButtonRef.current?.focus();
      }
    };

    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        onClose();
        if (triggerButtonRef.current && !triggerButtonRef.current.contains(e.target as Node)) {
          triggerButtonRef.current.focus();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('mousedown', handleClickOutside);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen, onClose]);

  const handleTargetModeKeyDown = (e: React.KeyboardEvent, index: number) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const next = (index + 1) % TARGET_MODES.length;
      targetModeRefs.current[next]?.focus();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const prev = (index - 1 + TARGET_MODES.length) % TARGET_MODES.length;
      targetModeRefs.current[prev]?.focus();
    } else if (e.key === 'Home') {
      e.preventDefault();
      targetModeRefs.current[0]?.focus();
    } else if (e.key === 'End') {
      e.preventDefault();
      targetModeRefs.current[TARGET_MODES.length - 1]?.focus();
    } else if (e.key === 'Tab' && e.shiftKey) {
      e.preventDefault();
      const activeResIdx = RESOLUTION_OPTIONS.findIndex((r) => r.dpi === currentDpi);
      const targetIdx = activeResIdx >= 0 ? activeResIdx : 0;
      resolutionRefs.current[targetIdx]?.focus();
    }
  };

  const handleResolutionKeyDown = (e: React.KeyboardEvent, index: number) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const next = (index + 1) % RESOLUTION_OPTIONS.length;
      resolutionRefs.current[next]?.focus();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const prev = (index - 1 + RESOLUTION_OPTIONS.length) % RESOLUTION_OPTIONS.length;
      resolutionRefs.current[prev]?.focus();
    } else if (e.key === 'Home') {
      e.preventDefault();
      resolutionRefs.current[0]?.focus();
    } else if (e.key === 'End') {
      e.preventDefault();
      resolutionRefs.current[RESOLUTION_OPTIONS.length - 1]?.focus();
    } else if (e.key === 'Tab' && !e.shiftKey) {
      e.preventDefault();
      const activeTargetIdx = TARGET_MODES.findIndex((t) => t.mode === taskMode);
      const targetIdx = activeTargetIdx >= 0 ? activeTargetIdx : 0;
      targetModeRefs.current[targetIdx]?.focus();
    }
  };

  const activeMode = TARGET_MODES.find((m) => m.mode === taskMode);

  return (
    <div className="relative inline-flex items-center" ref={popoverRef}>
      <button
        ref={triggerButtonRef}
        type="button"
        onClick={onToggleOpen}
        className="h-8 px-2.5 bg-white/[0.04] hover:bg-white/[0.08] text-[#F3F3F3] rounded-md text-xs font-medium flex items-center gap-1.5 border border-white/8 active:scale-[0.98] transition-all duration-100 ease-out cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
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
          className="absolute left-0 top-9 w-[290px] bg-[#272727] dark:bg-[var(--bg-elevated)] rounded-lg border border-white/10 shadow-[0_8px_16px_rgba(0,0,0,0.36)] py-1.5 z-30 text-[13px] origin-top-left animate-dropdown"
          role="dialog"
          aria-modal="false"
          aria-label="Extraction Options"
        >
          {/* Section 1: EXTRACTION TARGET */}
          <div className="px-3 py-1 text-2xs font-semibold uppercase tracking-wider text-[#A6A6A6] border-b border-white/8 mb-1">
            EXTRACTION TARGET
          </div>
          <div role="radiogroup" aria-label="Extraction Target Modes">
            {TARGET_MODES.map((tm, idx) => (
              <button
                key={tm.mode}
                ref={(el) => {
                  targetModeRefs.current[idx] = el;
                }}
                type="button"
                role="radio"
                aria-checked={taskMode === tm.mode}
                tabIndex={taskMode === tm.mode ? 0 : -1}
                onClick={() => onSelectMode(tm.mode)}
                onKeyDown={(e) => handleTargetModeKeyDown(e, idx)}
                className={`w-full text-left px-3 py-1.5 hover:bg-white/[0.08] flex items-center justify-between cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none transition-colors ${
                  taskMode === tm.mode ? 'bg-[#60CDFF]/15' : ''
                }`}
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
          <div role="radiogroup" aria-label="Scan Detail Resolution">
            {RESOLUTION_OPTIONS.map((res, idx) => (
              <button
                key={res.dpi}
                ref={(el) => {
                  resolutionRefs.current[idx] = el;
                }}
                type="button"
                role="radio"
                aria-checked={currentDpi === res.dpi}
                tabIndex={currentDpi === res.dpi ? 0 : -1}
                onClick={() => onSelectDpi(res.dpi)}
                onKeyDown={(e) => handleResolutionKeyDown(e, idx)}
                className={`w-full text-left px-3 py-1.5 hover:bg-white/[0.08] flex items-center justify-between cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none transition-colors ${
                  currentDpi === res.dpi ? 'bg-[#60CDFF]/15' : ''
                }`}
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
