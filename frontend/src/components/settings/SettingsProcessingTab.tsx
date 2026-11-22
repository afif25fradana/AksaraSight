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
      {/* DPI Selection Section */}
      <div className="space-y-2.5">
        <div className="flex justify-between items-center">
          <div>
            <h3 className="text-[13.5px] font-semibold text-[#F3F3F3]">
              Document Render Resolution (DPI)
            </h3>
            <p className="text-[11.5px] text-[#A6A6A6] mt-0.5">
              Default rasterization resolution for OCR scans. Synchronized across workspace scan options.
            </p>
          </div>
          <span 
            className="font-mono text-[12.5px] font-bold text-[#60CDFF] px-2.5 py-0.5 rounded-sm bg-[#60CDFF]/10 border border-[#60CDFF]/30" 
            style={{ fontVariantNumeric: 'tabular-nums' }}
          >
            {formData.dpi} DPI
          </span>
        </div>

        {/* Interactive DPI Preset Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5" role="group" aria-label="Document Render Resolution">
          {DPI_OPTIONS.map((option) => {
            const isSelected = formData.dpi === option.dpi;
            return (
              <button
                key={option.dpi}
                type="button"
                aria-pressed={isSelected}
                aria-label={`${option.dpi} DPI`}
                onClick={() => setFormData((prev) => ({ ...prev, dpi: option.dpi }))}
                className={`p-3.5 rounded-lg border text-left cursor-pointer transition-all duration-150 flex flex-col justify-between focus:outline-none focus-visible:ring-2 focus-visible:ring-[#60CDFF] active:scale-[0.98] ${
                  isSelected
                    ? 'bg-[#60CDFF]/10 border-[#60CDFF] ring-1 ring-[#60CDFF]/30 shadow-xs'
                    : 'bg-[#272727] border-white/[0.08] hover:border-white/[0.16] hover:bg-[#2d2d2d]'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className={`font-mono text-[13px] font-bold ${
                    isSelected
                      ? 'text-[#60CDFF]'
                      : 'text-[#F3F3F3]'
                  }`}>
                    {option.dpi} DPI
                  </span>
                  <div className={`w-3.5 h-3.5 rounded-full border flex items-center justify-center transition-colors ${
                    isSelected
                      ? 'border-[#60CDFF] bg-[#60CDFF]'
                      : 'border-white/20 bg-transparent'
                  }`}>
                    {isSelected && (
                      <div className="w-1.5 h-1.5 rounded-full bg-[#000000]" />
                    )}
                  </div>
                </div>
                <span className={`text-[11.5px] leading-relaxed ${
                  isSelected
                    ? 'text-[#60CDFF]/90 font-medium'
                    : 'text-[#A6A6A6]'
                }`}>
                  {option.desc}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Limits Grid */}
      <div className="bg-[#272727] p-4 rounded-lg border border-white/[0.06] grid grid-cols-2 gap-4 transition-colors">
        <div>
          <label className="block text-[13px] font-medium text-[#F3F3F3] mb-1" htmlFor="max-image-size">
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
              className="w-full max-w-[120px] h-[34px] px-2.5 text-[13.5px] bg-white/[0.03] border border-white/[0.06] rounded-md text-[#F3F3F3] focus:outline-none focus:border-[#60CDFF] focus:ring-1 focus:ring-[#60CDFF]" 
            />
            <span className="text-[12px] text-[#A6A6A6]">px</span>
          </div>
          <p className="text-[11.5px] text-[#A6A6A6] mt-1">
            Images exceeding this dimension are downscaled before inference
          </p>
        </div>

        <div>
          <label className="block text-[13px] font-medium text-[#F3F3F3] mb-1" htmlFor="max-tokens">
            Max Tokens Per Page
          </label>
          <input 
            id="max-tokens" 
            type="number" 
            min={128}
            max={16384}
            value={formData.max_tokens}
            onChange={(e) => setFormData((prev) => ({ ...prev, max_tokens: Number(e.target.value) }))}
            className="w-full max-w-[120px] h-[34px] px-2.5 text-[13.5px] bg-white/[0.03] border border-white/[0.06] rounded-md text-[#F3F3F3] focus:outline-none focus:border-[#60CDFF] focus:ring-1 focus:ring-[#60CDFF]" 
          />
          <p className="text-[11.5px] text-[#A6A6A6] mt-1">
            Context window token budget reserved for each page's OCR output
          </p>
        </div>
      </div>
    </div>
  );
};
