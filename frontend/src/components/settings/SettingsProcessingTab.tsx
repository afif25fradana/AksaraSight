import React from 'react';
import { BackendSettings } from '../../types';

export const DPI_OPTIONS: { dpi: number; desc: string }[] = [
  { dpi: 72, desc: 'Draft / Fast preview' },
  { dpi: 100, desc: 'Standard documents (Recommended)' },
  { dpi: 150, desc: 'High resolution / Small fonts' },
  { dpi: 200, desc: 'Archival / Fine manuscript detail' },
];

export interface SettingsProcessingTabProps {
  formData: BackendSettings;
  setFormData: React.Dispatch<React.SetStateAction<BackendSettings>>;
}

export const SettingsProcessingTab: React.FC<SettingsProcessingTabProps> = ({
  formData,
  setFormData,
}) => {
  return (
    <div className="space-y-4 animate-fade-in">
      {/* DPI Selection Block */}
      <div className="bg-white dark:bg-[var(--bg-elevated)] p-4 rounded-lg border border-[#8A94A6]/25 dark:border-[var(--border)] space-y-3 transition-colors">
        <div className="flex justify-between items-center">
          <div>
            <h3 className="text-[13.5px] font-semibold text-[#14213D] dark:text-[var(--text-1)]">
              Document Render Resolution (DPI)
            </h3>
            <p className="text-[11.5px] text-[#5A6478] dark:text-[var(--text-2)] mt-0.5">
              Default rasterization resolution for OCR scans. Synchronized across workspace scan options.
            </p>
          </div>
          <span 
            className="font-mono text-[12.5px] font-bold text-[#0F766E] dark:text-[var(--accent)] px-2.5 py-0.5 rounded bg-[#0F766E]/10 dark:bg-[var(--accent)]/10 border border-[#0F766E]/25 dark:border-[var(--accent)]/30" 
            style={{ fontVariantNumeric: 'tabular-nums' }}
          >
            {formData.dpi} DPI
          </span>
        </div>

        {/* Interactive DPI Preset Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 pt-1" role="group" aria-label="Document Render Resolution">
          {DPI_OPTIONS.map((option) => {
            const isSelected = formData.dpi === option.dpi;
            return (
              <button
                key={option.dpi}
                type="button"
                aria-pressed={isSelected}
                aria-label={`${option.dpi} DPI`}
                onClick={() => setFormData((prev) => ({ ...prev, dpi: option.dpi }))}
                className={`p-3 rounded-lg border text-left cursor-pointer transition-all duration-150 flex flex-col justify-between focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0F766E] dark:focus-visible:ring-[var(--accent)] active:scale-[0.98] ${
                  isSelected
                    ? 'bg-[#0F766E]/10 dark:bg-[var(--accent)]/10 border-[#0F766E] dark:border-[var(--accent)] ring-1 ring-[#0F766E]/30 dark:ring-[var(--accent)]/30 shadow-xs'
                    : 'bg-[#FAF9F5] dark:bg-[var(--bg-base)] border-[#8A94A6]/20 dark:border-[var(--border)] hover:border-[#8A94A6]/40 dark:hover:border-[#5A6478]'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className={`font-mono text-[13px] font-bold ${
                    isSelected
                      ? 'text-[#0F766E] dark:text-[var(--accent)]'
                      : 'text-[#14213D] dark:text-[var(--text-1)]'
                  }`}>
                    {option.dpi} DPI
                  </span>
                  <div className={`w-3.5 h-3.5 rounded-full border flex items-center justify-center transition-colors ${
                    isSelected
                      ? 'border-[#0F766E] dark:border-[var(--accent)] bg-[#0F766E] dark:bg-[var(--accent)]'
                      : 'border-[#8A94A6]/40 dark:border-[var(--border)] bg-transparent'
                  }`}>
                    {isSelected && (
                      <div className="w-1.5 h-1.5 rounded-full bg-white dark:bg-[#121417]" />
                    )}
                  </div>
                </div>
                <span className={`text-[11.5px] leading-relaxed ${
                  isSelected
                    ? 'text-[#0F766E]/90 dark:text-[var(--accent)]/90 font-medium'
                    : 'text-[#5A6478] dark:text-[var(--text-2)]'
                }`}>
                  {option.desc}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Limits Grid */}
      <div className="bg-white dark:bg-[var(--bg-elevated)] p-4 rounded-lg border border-[#E5E2D9] dark:border-[var(--border)] grid grid-cols-2 gap-4 transition-colors">
        <div>
          <label className="block text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)] mb-1" htmlFor="max-image-size">
            Max Image Dimension
          </label>
          <div className="flex items-center gap-2">
            <input 
              id="max-image-size" 
              type="number" 
              min={512}
              max={8192}
              value={formData.max_image_dimension}
              onChange={(e) => setFormData((prev) => ({ ...prev, max_image_dimension: Number(e.target.value) }))}
              className="w-full max-w-[120px] h-[34px] px-2.5 text-[13.5px] bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md text-[#14213D] dark:text-[var(--text-1)] focus:outline-none focus:border-[#0F766E] dark:focus:border-[var(--accent)] focus:ring-1 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)]" 
            />
            <span className="text-[12px] text-[#4B5563] dark:text-[var(--text-2)]">px</span>
          </div>
          <p className="text-[11.5px] text-[#4B5563] dark:text-[var(--text-2)] mt-1">
            Images exceeding this dimension are downscaled before inference
          </p>
        </div>

        <div>
          <label className="block text-[13px] font-medium text-[#14213D] dark:text-[var(--text-1)] mb-1" htmlFor="max-tokens">
            Max Tokens Per Page
          </label>
          <input 
            id="max-tokens" 
            type="number" 
            min={128}
            max={16384}
            value={formData.max_tokens}
            onChange={(e) => setFormData((prev) => ({ ...prev, max_tokens: Number(e.target.value) }))}
            className="w-full max-w-[120px] h-[34px] px-2.5 text-[13.5px] bg-[#FAF9F5] dark:bg-[var(--bg-base)] border border-[#E5E2D9] dark:border-[var(--border)] rounded-md text-[#14213D] dark:text-[var(--text-1)] focus:outline-none focus:border-[#0F766E] dark:focus:border-[var(--accent)] focus:ring-1 focus:ring-[#0F766E] dark:focus:ring-[var(--accent)]" 
          />
          <p className="text-[11.5px] text-[#4B5563] dark:text-[var(--text-2)] mt-1">
            Context window token budget reserved for each page's OCR output
          </p>
        </div>
      </div>
    </div>
  );
};
