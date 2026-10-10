import React, { useState } from 'react';
import { ScrollText, ChevronLeft, ChevronRight, Minus, Plus, Maximize2 } from 'lucide-react';
import { DocumentItem } from '../types';

interface DocumentPreviewPanelProps {
  document: DocumentItem | null;
  onPageChange: (newPage: number) => void;
}

export const DocumentPreviewPanel: React.FC<DocumentPreviewPanelProps> = ({
  document,
  onPageChange,
}) => {
  const [zoomLevel, setZoomLevel] = useState<number>(100);

  const handleZoomIn = () => {
    setZoomLevel((prev) => Math.min(prev + 25, 200));
  };

  const handleZoomOut = () => {
    setZoomLevel((prev) => Math.max(prev - 25, 50));
  };

  const handleZoomReset = () => {
    setZoomLevel(100);
  };

  if (!document) {
    return (
      <main 
        aria-label="Document preview empty" 
        className="lg:col-span-5 flex flex-col bg-[#FAF9F5] dark:bg-[var(--bg-surface)] rounded-xl border border-[#8A94A6]/30 dark:border-[var(--border)] overflow-hidden h-full transition-colors"
      >
        <div className="h-12 px-4 border-b border-[#8A94A6]/25 dark:border-[var(--border)] flex items-center justify-between shrink-0 bg-[#FAF9F5] dark:bg-[var(--bg-surface)]">
          <h2 className="font-['IBM_Plex_Sans',sans-serif] text-[14px] font-semibold text-[#14213D] dark:text-[var(--text-1)]">
            Document Preview
          </h2>
        </div>
        <div className="h-11 px-3 border-b border-[#8A94A6]/25 dark:border-[var(--border)] flex items-center justify-between bg-white/70 dark:bg-[var(--bg-surface)]/90 backdrop-blur-sm shrink-0 text-[#5A6478] dark:text-[var(--text-2)] text-[13px] select-none">
          <div className="flex items-center gap-1 opacity-50">
            <span className="h-7 px-2 flex items-center gap-1 font-medium text-[12.5px]">Previous</span>
            <span className="px-2 text-[12.5px] tabular-nums">0 of 0</span>
            <span className="h-7 px-2 flex items-center gap-1 font-medium text-[12.5px]">Next</span>
          </div>
          <div className="flex items-center gap-1 opacity-50">
            <span className="h-7 px-2 flex items-center font-medium text-[12.5px]">Fit</span>
          </div>
        </div>
        <div className="flex-1 bg-[#EAE8E1]/60 dark:bg-[var(--bg-base)] p-6 flex flex-col items-center justify-center text-center select-none">
          <div className="w-12 h-12 rounded-full bg-[#14213D]/[0.05] dark:bg-white/[0.05] border border-[#14213D]/[0.08] dark:border-[var(--border)] flex items-center justify-center mb-3 text-[#5A6478] dark:text-[var(--text-3)] shadow-xs">
            <ScrollText className="w-6 h-6 text-[#5A6478] dark:text-[var(--text-3)]" aria-hidden="true" />
          </div>
          <p className="font-semibold text-[14px] text-[#14213D] dark:text-[var(--text-1)] mb-1">
            No document selected
          </p>
          <p className="text-[12.5px] text-[#5A6478] dark:text-[var(--text-2)] max-w-xs leading-relaxed">
            Select any file from the queue to preview its contents
          </p>
        </div>
      </main>
    );
  }

  const currentPage = document.currentPage || 1;
  const totalPages = document.pages;

  return (
    <main 
      aria-label="Document preview" 
      className="lg:col-span-5 flex flex-col bg-[#FAF9F5] dark:bg-[var(--bg-surface)] rounded-xl border border-[#8A94A6]/30 dark:border-[var(--border)] overflow-hidden h-full transition-colors"
    >
      {/* Header - Clean file title */}
      <div className="h-12 px-4 border-b border-[#8A94A6]/25 dark:border-[var(--border)] flex items-center justify-between shrink-0 bg-[#FAF9F5] dark:bg-[var(--bg-surface)]">
        <div className="flex items-center gap-2 truncate">
          <h2 className="font-['IBM_Plex_Sans',sans-serif] text-[14px] font-semibold text-[#14213D] dark:text-[var(--text-1)] truncate" title={document.name}>
            {document.name}
          </h2>
        </div>
      </div>

      {/* Toolbar: Ghost utility style for frequent utilities (Previous/Next, zoom, Fit) */}
      <div className="h-11 px-3 border-b border-[#8A94A6]/25 dark:border-[var(--border)] flex items-center justify-between bg-white/70 dark:bg-[var(--bg-surface)]/90 backdrop-blur-sm shrink-0">
        {/* Pager utility */}
        <div className="flex items-center gap-1">
          <button 
            disabled={currentPage <= 1}
            onClick={() => onPageChange(Math.max(1, currentPage - 1))}
            className="h-7 px-2.5 rounded-md hover:bg-black/5 dark:bg-[var(--bg-elevated)] dark:border dark:border-[var(--border)] dark:hover:bg-[var(--bg-active)] disabled:opacity-30 disabled:hover:bg-transparent text-[#14213D] dark:text-[var(--text-1)] transition-colors active:scale-90 active:translate-y-px transition-all duration-100 ease-out flex items-center gap-1 text-[12.5px] font-medium cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none" 
            type="button" 
            aria-label="Previous"
          >
            <ChevronLeft className="w-4 h-4 leading-none" aria-hidden="true" />
            <span>Previous</span>
          </button>

          <span className="text-[12.5px] tabular-nums font-medium px-1.5 text-[#14213D] dark:text-[var(--text-1)] select-none" aria-live="polite">
            {currentPage} of {totalPages}
          </span>

          <button 
            disabled={currentPage >= totalPages}
            onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
            className="h-7 px-2.5 rounded-md hover:bg-black/5 dark:bg-[var(--bg-elevated)] dark:border dark:border-[var(--border)] dark:hover:bg-[var(--bg-active)] disabled:opacity-30 disabled:hover:bg-transparent text-[#14213D] dark:text-[var(--text-1)] transition-colors active:scale-90 active:translate-y-px transition-all duration-100 ease-out flex items-center gap-1 text-[12.5px] font-medium cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none" 
            type="button" 
            aria-label="Next"
          >
            <span>Next</span>
            <ChevronRight className="w-4 h-4 leading-none" aria-hidden="true" />
          </button>
        </div>

        {/* Zoom & Fit utilities (Ghost style) */}
        <div className="flex items-center gap-1">
          <div className="inline-flex items-center rounded-md p-0.5 bg-black/[0.03] dark:bg-[var(--bg-elevated)] border border-black/[0.06] dark:border-[var(--border)]">
            <button 
              onClick={handleZoomOut}
              className="w-7 h-7 rounded hover:bg-black/5 dark:hover:bg-[var(--bg-active)] text-[#14213D] dark:text-[var(--text-1)] transition-colors active:scale-90 active:translate-y-px transition-all duration-100 ease-out flex items-center justify-center cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none" 
              title="Zoom out" 
              aria-label="Zoom out" 
              type="button" 
            >
              <Minus className="w-4 h-4 leading-none" aria-hidden="true" />
            </button>
            <span className="text-[12px] tabular-nums font-medium text-[#14213D] dark:text-[var(--text-1)] px-1.5 min-w-[42px] text-center select-none" aria-label={`Current zoom level ${zoomLevel}%`}>
              {zoomLevel}%
            </span>
            <button 
              onClick={handleZoomIn}
              className="w-7 h-7 rounded hover:bg-black/5 dark:hover:bg-[var(--bg-active)] text-[#14213D] dark:text-[var(--text-1)] transition-colors active:scale-90 active:translate-y-px transition-all duration-100 ease-out flex items-center justify-center cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none" 
              title="Zoom in" 
              aria-label="Zoom in" 
              type="button" 
            >
              <Plus className="w-4 h-4 leading-none" aria-hidden="true" />
            </button>
          </div>

          <div className="w-px h-3.5 bg-black/10 dark:bg-[var(--border)] mx-0.5" />

          <button 
            onClick={handleZoomReset}
            className="h-7 px-2.5 rounded-md hover:bg-black/5 dark:bg-[var(--bg-elevated)] dark:border dark:border-[var(--border)] dark:hover:bg-[var(--bg-active)] text-[#14213D] dark:text-[var(--text-1)] transition-colors active:scale-90 active:translate-y-px transition-all duration-100 ease-out flex items-center gap-1 text-[12.5px] font-medium cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none" 
            title="Fit" 
            aria-label="Fit" 
            type="button" 
          >
            <Maximize2 className="w-3.5 h-3.5 leading-none" aria-hidden="true" />
            <span>Fit</span>
          </button>
        </div>
      </div>

      {/* Document Viewport / Canvas */}
      <div className="flex-1 bg-[#EAE8E1]/60 dark:bg-[var(--bg-base)] p-4 overflow-y-auto flex justify-center items-start transition-colors">
        <div 
          style={{ transform: `scale(${zoomLevel / 100})`, transformOrigin: 'top center' }}
          className="transition-transform duration-150 w-full flex justify-center"
        >
          {document.previewImageUrl ? (
            <div className="w-full max-w-[560px] bg-white dark:bg-[var(--paper-bg)] border border-[#14213D]/12 dark:border-[var(--paper-border)] rounded-[4px] shadow-[0_4px_16px_rgba(20,33,61,0.07)] dark:shadow-[0_4px_24px_rgba(0,0,0,0.5)] p-3 flex justify-center">
              <img 
                src={document.previewImageUrl} 
                alt={`${document.name} page ${currentPage}`}
                className="max-w-full h-auto object-contain rounded"
              />
            </div>
          ) : document.docType === 'legal-agreement' ? (
            /* SURAT PERJANJIAN KERJASAMA (Realistic paper presence in light & dark mode) */
            <article 
              className="facsimile-sheet w-full max-w-[480px] bg-[#FCFBF8] dark:bg-[var(--paper-bg)] border border-[#14213D]/12 dark:border-[var(--paper-border)] rounded-[2px] shadow-[0_4px_16px_rgba(20,33,61,0.07),0_1px_3px_rgba(20,33,61,0.05)] dark:shadow-[0_4px_24px_rgba(0,0,0,0.5),0_1px_4px_rgba(0,0,0,0.3)] p-6 text-[#1A1A1A] dark:text-[var(--paper-text)] relative select-text transition-colors" 
              aria-label="Simulated Archival Document"
            >
              {/* Official Letterhead */}
              <div className="border-b-2 border-black/80 pb-3 mb-4 text-center">
                <p className="text-[10px] tracking-widest text-[#374151] mb-0.5 uppercase font-medium">
                  REPUBLIK INDONESIA - ARSIP DAERAH
                </p>
                <h3 className="font-['IBM_Plex_Serif',serif] text-[15px] font-bold text-[#1A1A1A] uppercase tracking-wide">
                  KANTOR NOTARIS & PPAT WIJAYA, S.H.
                </h3>
                <p className="text-[10.5px] text-[#374151]">
                  Jl. Braga No. 42, Kota Bandung, Jawa Barat | Telp: (022) 420-1192
                </p>
              </div>

              {/* Title & Document Number */}
              <div className="text-center mb-4">
                <h4 className="font-['IBM_Plex_Serif',serif] text-[13px] font-bold text-[#1A1A1A] underline tracking-wide">
                  SURAT PERJANJIAN KERJASAMA
                </h4>
                <p className="text-[11px] text-[#374151] mt-0.5 font-mono">
                  Nomor: 042/SPK/AKS/XI/2023
                </p>
              </div>

              {/* Body Text */}
              <div lang="id" className="text-xs leading-relaxed font-serif-brand text-[#1A1A1A] dark:text-[var(--paper-text)] space-y-2.5 text-justify hyphens-auto">
                <p>
                  Pada hari ini, <span className="font-semibold text-[#1A1A1A]">Senin tanggal dua puluh November tahun dua ribu dua puluh tiga</span> (20-11-2023), bertempat di Bandung, yang bertanda tangan di bawah ini:
                </p>

                <div className="pl-3 border-l-2 border-[#1A1A1A]/20 space-y-1 text-[11px]">
                  <p>
                    <span className="font-semibold text-[#1A1A1A]">I. Dr. Hendra Gunawan</span>, bertindak atas nama Balai Konservasi Naskah Kuno selanjutnya disebut sebagai <span className="font-semibold text-[#1A1A1A]">PIHAK PERTAMA</span>.
                  </p>
                  <p>
                    <span className="font-semibold text-[#1A1A1A]">II. AksaraSight Lab</span>, unit pelaksana pemrosesan data lokal selanjutnya disebut sebagai <span className="font-semibold text-[#1A1A1A]">PIHAK KEDUA</span>.
                  </p>
                </div>

                <p>
                  Para pihak sepakat mengadakan perjanjian pemindaian dan preservasi naskah arsip digital dengan ketentuan bahwa seluruh data diproses secara lokal tanpa transmisi pihak ketiga.
                </p>

                <p>
                  Segala bentuk hasil transkripsi teks optik akan diverifikasi secara langsung menggunakan parameter pencocokan karakter minimum 98%.
                </p>
              </div>

              {/* Signatures */}
              <div className="mt-8 pt-4 border-t border-[#1A1A1A]/15 grid grid-cols-2 text-center text-[10.5px]">
                <div>
                  <p className="text-[#374151]">PIHAK PERTAMA,</p>
                  <div className="h-10 flex items-center justify-center my-1 text-[#1A1A1A]/40 italic font-['IBM_Plex_Serif',serif]">
                    [Tanda Tangan & Cap]
                  </div>
                  <p className="font-semibold text-[#1A1A1A] underline">Dr. Hendra Gunawan</p>
                  <p className="text-[9.5px] text-[#4B5563] font-mono">NIP. 19740512 199903 1 002</p>
                </div>
                <div>
                  <p className="text-[#374151]">PIHAK KEDUA,</p>
                  <div className="h-10 flex items-center justify-center my-1 text-[#1A1A1A]/40 italic font-['IBM_Plex_Serif',serif]">
                    [Tanda Tangan Elektronik]
                  </div>
                  <p className="font-semibold text-[#1A1A1A] underline">AksaraSight Core</p>
                </div>
              </div>
            </article>
          ) : document.docType === 'invoice' ? (
            /* FAKTUR PENJUALAN */
            <div 
              role="region" 
              aria-label={`Document preview: ${document.name}, page ${currentPage} of ${totalPages}`} 
              className="w-full max-w-[480px] bg-[#FCFBF8] dark:bg-[var(--paper-bg)] border border-[#14213D]/12 dark:border-[var(--paper-border)] rounded-[2px] shadow-[0_4px_16px_rgba(20,33,61,0.07),0_1px_3px_rgba(20,33,61,0.05)] dark:shadow-[0_4px_24px_rgba(0,0,0,0.5),0_1px_4px_rgba(0,0,0,0.3)] p-6 text-[#1A1A1A] dark:text-[var(--paper-text)] relative select-text transition-colors"
            >
              <div className="border-b-2 border-[#14213D] pb-4 mb-6 flex justify-between items-baseline">
                <div>
                  <h1 className="text-[19px] font-bold tracking-tight text-[#14213D] font-['IBM_Plex_Serif',serif]">
                    FAKTUR PENJUALAN
                  </h1>
                  <p className="text-[11.5px] font-['IBM_Plex_Sans',sans-serif] text-[#4B5563] tracking-widest mt-0.5">
                    COMMERCIAL TAX INVOICE
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-[13px] font-['IBM_Plex_Sans',sans-serif] font-bold text-[#14213D]">
                    No: INV-2023-003
                  </p>
                  <p className="text-[11.5px] font-['IBM_Plex_Sans',sans-serif] text-[#4B5563]">
                    Date: 14/10/2023
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-6 mb-6 text-[12.5px] leading-relaxed border-b border-[#E2DFD6] pb-5">
                <div>
                  <span className="text-[10px] font-['IBM_Plex_Sans',sans-serif] font-semibold uppercase text-[#4B5563] block mb-1">
                    Diterbitkan Oleh (Vendor):
                  </span>
                  <p className="font-semibold text-[#14213D]">PT. NUSANTARA SISTEM GRAFIKA</p>
                  <p className="text-[#374151]">Jl. Raden Saleh No. 42A, Cikini</p>
                  <p className="text-[#374151]">Jakarta Pusat 10330 - ID</p>
                  <p className="text-[11px] font-['IBM_Plex_Sans',sans-serif] text-[#4B5563] mt-1">
                    NPWP: 01.423.890.4-021.000
                  </p>
                </div>
                <div>
                  <span className="text-[10px] font-['IBM_Plex_Sans',sans-serif] font-semibold uppercase text-[#4B5563] block mb-1">
                    Tagihan Kepada (Billed To):
                  </span>
                  <p className="font-semibold text-[#14213D]">ARSIP NASIONAL REPUBLIKA</p>
                  <p className="text-[#374151]">Divisi Preservasi Manuskrip</p>
                  <p className="text-[#374151]">Gedung Arsip B, Lantai 3</p>
                  <p className="text-[11px] font-['IBM_Plex_Sans',sans-serif] text-[#4B5563] mt-1">
                    PO Ref: PO-PRE-8842
                  </p>
                </div>
              </div>

              <table className="w-full text-left border-collapse mb-6">
                <thead>
                  <tr className="border-b border-[#14213D] text-[10.5px] font-['IBM_Plex_Sans',sans-serif] text-[#4B5563] uppercase">
                    <th className="py-1.5 font-semibold">Item & Description</th>
                    <th className="py-1.5 text-center font-semibold w-16">Qty</th>
                    <th className="py-1.5 text-right font-semibold w-24">Rate (IDR)</th>
                    <th className="py-1.5 text-right font-semibold w-28">Total (IDR)</th>
                  </tr>
                </thead>
                <tbody className="text-[12px] divide-y divide-[#E2DFD6]/60">
                  <tr className="hover:bg-black/[0.02]">
                    <td className="py-2.5 pr-2">
                      <p className="font-medium text-[#14213D]">Konservasi Kertas Bebas Asam (pH 8.5)</p>
                      <p className="text-[11px] font-['IBM_Plex_Sans',sans-serif] text-[#4B5563]">Grade A75 Archival Lining Paper</p>
                    </td>
                    <td className="py-2.5 text-center font-['IBM_Plex_Sans',sans-serif] text-[#374151]">10 Rim</td>
                    <td className="py-2.5 text-right font-['IBM_Plex_Sans',sans-serif] text-[#374151]">850.000</td>
                    <td className="py-2.5 text-right font-['IBM_Plex_Sans',sans-serif] font-medium text-[#14213D]">8.500.000</td>
                  </tr>
                  <tr className="hover:bg-black/[0.02]">
                    <td className="py-2.5 pr-2">
                      <p className="font-medium text-[#14213D]">Methyl Cellulose Adhesive (High Viscosity)</p>
                      <p className="text-[11px] font-['IBM_Plex_Sans',sans-serif] text-[#4B5563]">Kemasan 1000g food-grade safe</p>
                    </td>
                    <td className="py-2.5 text-center font-['IBM_Plex_Sans',sans-serif] text-[#374151]">4 Jar</td>
                    <td className="py-2.5 text-right font-['IBM_Plex_Sans',sans-serif] text-[#374151]">320.000</td>
                    <td className="py-2.5 text-right font-['IBM_Plex_Sans',sans-serif] font-medium text-[#14213D]">1.280.000</td>
                  </tr>
                  <tr className="hover:bg-black/[0.02]">
                    <td className="py-2.5 pr-2">
                      <p className="font-medium text-[#14213D]">Micro-Chamber Archival Storage Folio</p>
                      <p className="text-[11px] font-['IBM_Plex_Sans',sans-serif] text-[#4B5563]">Ukuran Folio Standard 38x26 cm</p>
                    </td>
                    <td className="py-2.5 text-center font-['IBM_Plex_Sans',sans-serif] text-[#374151]">50 Unit</td>
                    <td className="py-2.5 text-right font-['IBM_Plex_Sans',sans-serif] text-[#374151]">45.000</td>
                    <td className="py-2.5 text-right font-['IBM_Plex_Sans',sans-serif] font-medium text-[#14213D]">2.250.000</td>
                  </tr>
                </tbody>
              </table>

              <div className="border-t border-[#14213D] pt-3">
                <div className="flex justify-end">
                  <div className="w-56 space-y-1.5 text-[12px] font-['IBM_Plex_Sans',sans-serif]">
                    <div className="flex justify-between text-[#4B5563]">
                      <span>Subtotal:</span>
                      <span>12.030.000</span>
                    </div>
                    <div className="flex justify-between text-[#4B5563]">
                      <span>PPN (11%):</span>
                      <span>1.323.300</span>
                    </div>
                    <div className="flex justify-between border-t border-[#14213D] pt-1.5 text-[14px] font-bold text-[#14213D]">
                      <span>TOTAL:</span>
                      <span>IDR 13.353.300</span>
                    </div>
                  </div>
                </div>

                <div className="mt-6 pt-3 border-t border-dashed border-[#E2DFD6] flex justify-between items-end text-[10.5px] font-['IBM_Plex_Sans',sans-serif] text-[#4B5563]">
                  <div>
                    <p>Transfer: Bank Mandiri 122-00-9831920-1</p>
                    <p>Status: LUNAS (PAID 15/10/2023)</p>
                  </div>
                  <div className="text-right italic">
                    <span>Verification Hash: 8bfa92e10a</span>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            /* HISTORICAL ARSIP / OTHER DOCUMENT */
            <div 
              role="region" 
              aria-label={`Document preview: ${document.name}, page ${currentPage} of ${totalPages}`}
              className="w-full max-w-[480px] bg-[#FCFBF8] dark:bg-[var(--paper-bg)] border border-[#14213D]/12 dark:border-[var(--paper-border)] rounded-[2px] shadow-[0_4px_16px_rgba(20,33,61,0.07),0_1px_3px_rgba(20,33,61,0.05)] dark:shadow-[0_4px_24px_rgba(0,0,0,0.5),0_1px_4px_rgba(0,0,0,0.3)] p-6 text-[#1A1A1A] dark:text-[var(--paper-text)] relative select-text transition-colors"
            >
              <div className="border-b-2 border-black/80 pb-3 mb-4 flex justify-between items-start">
                <div>
                  <p className="text-[10px] tracking-widest text-[#374151] uppercase font-mono font-medium">
                    KOLEKSI MANUSKRIP ARSIP
                  </p>
                  <h3 className="font-['IBM_Plex_Serif',serif] text-[15px] font-bold text-[#1A1A1A] uppercase">
                    {document.name}
                  </h3>
                </div>
                <span className="text-[11px] font-mono text-[#4B5563]">
                  Page {currentPage} of {totalPages}
                </span>
              </div>

              {document.previewImageUrl ? (
                <div className="my-4 border border-black/10 rounded overflow-hidden">
                  <img 
                    src={document.previewImageUrl} 
                    alt={document.name} 
                    className="w-full h-auto object-contain max-h-[360px]"
                  />
                </div>
              ) : (
                <div className="text-[12px] font-['IBM_Plex_Serif',serif] leading-relaxed text-[#2D3139] space-y-3">
                  <p className="italic text-[#4B5563]">
                    [Archival document preview. Extracted text is displayed in the right panel.]
                  </p>
                  {document.extractedText ? (
                    <div className="p-3 bg-[#F4F2EC] rounded border border-black/10 font-mono text-[11px] text-[#1A1A1A] whitespace-pre-wrap max-h-60 overflow-y-auto">
                      {document.extractedText.slice(0, 320)}...
                    </div>
                  ) : (
                    <div className="p-4 bg-black/[0.02] rounded border border-dashed border-[#8A94A6] text-center text-[#5A6478] text-[12px]">
                      Document has not been extracted yet.
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </main>
  );
};
