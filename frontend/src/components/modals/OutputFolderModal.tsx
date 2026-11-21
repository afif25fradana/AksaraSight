import React, { useState, useEffect } from 'react';
import { FolderOpen, X, Trash2, Eye, ExternalLink, Copy, Check, FileText } from 'lucide-react';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { useToast } from '../../hooks/useToast';
import { ExportedFile } from '../../types';

interface OutputFolderModalProps {
  isOpen: boolean;
  onClose: () => void;
  files: ExportedFile[];
  onDeleteFile: (id: string) => void;
  folderPath?: string;
}

export const OutputFolderModal: React.FC<OutputFolderModalProps> = ({
  isOpen,
  onClose,
  files,
  onDeleteFile,
  folderPath = '~/Documents/AksaraSight/output',
}) => {
  const { toast } = useToast();
  const [selectedFile, setSelectedFile] = useState<ExportedFile | null>(files[0] || null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [copiedPath, setCopiedPath] = useState(false);
  const [explorerOpenedFeedback, setExplorerOpenedFeedback] = useState<string | null>(null);
  const [isRendered, setIsRendered] = useState(isOpen);
  const [isClosing, setIsClosing] = useState(false);
  const modalRef = useFocusTrap<HTMLDivElement>(isRendered);

  useEffect(() => {
    if (isOpen) {
      setIsRendered(true);
      setIsClosing(false);
    } else if (isRendered) {
      setIsClosing(true);
      const timer = setTimeout(() => {
        setIsRendered(false);
        setIsClosing(false);
      }, 150);
      return () => clearTimeout(timer);
    }
  }, [isOpen, isRendered]);

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isRendered) return null;

  const effectiveFolderPath = folderPath || '~/Documents/AksaraSight/output';

  const handleCopyFolderPath = () => {
    navigator.clipboard.writeText(effectiveFolderPath);
    setCopiedPath(true);
    setTimeout(() => setCopiedPath(false), 2000);
  };

  const handleOpenInExplorer = async (filePath?: string) => {
    try {
      const res = await fetch('/api/output/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(filePath ? { path: filePath } : {}),
      });
      if (res.ok) {
        const body = await res.json().catch(() => ({ opened: false }));
        if (body.opened) {
          const feedbackText = filePath
            ? 'Revealed in File Explorer'
            : 'Opened in File Explorer';
          setExplorerOpenedFeedback(feedbackText);
          setTimeout(() => setExplorerOpenedFeedback(null), 3000);
        } else {
          setExplorerOpenedFeedback('Folder could not be opened on host system');
          setTimeout(() => setExplorerOpenedFeedback(null), 3000);
        }
      }
    } catch (err) {
      console.error('Failed to open in explorer:', err);
      setExplorerOpenedFeedback('Failed to request file explorer open');
      setTimeout(() => setExplorerOpenedFeedback(null), 3000);
    }
  };

  const handleDeleteFile = async (file: ExportedFile) => {
    try {
      const res = await fetch(`/api/output/${encodeURIComponent(file.filename)}`, { method: 'DELETE' });
      if (res.ok) {
        onDeleteFile(file.id);
        setDeleteConfirmId(null);
        setSelectedFile(null);
      } else {
        const errData = await res.json().catch(() => ({}));
        const errorMsg = errData.detail || errData.error || errData.message || `Failed to delete file (HTTP ${res.status})`;
        console.error('Failed to delete output file from disk:', errorMsg);
        toast.error(errorMsg);
      }
    } catch (err: any) {
      console.error('Failed to delete output file from disk:', err);
      toast.error(err?.message || 'Failed to delete file');
    }
  };

  return (
    <div 
      className={`fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-[4px] ${
        isClosing ? 'opacity-0 transition-opacity duration-150 ease-tactile pointer-events-none' : 'animate-modal-backdrop'
      }`}
      onClick={onClose}
    >
      <div 
        ref={modalRef}
        className={`w-full max-w-3xl bg-[#272727] rounded-lg border border-white/[0.08] shadow-xs will-change-transform overflow-hidden flex flex-col max-h-[88vh] text-[#F3F3F3] transition-colors ${
          isClosing ? 'animate-modal-window-exit' : 'animate-modal-window'
        }`}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="output-folder-title"
      >
        {/* Modal Header */}
        <div className="px-5 py-4 border-b border-white/[0.04] flex items-center justify-between bg-[#272727]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-md bg-[#60CDFF]/10 flex items-center justify-center text-[#60CDFF]">
              <FolderOpen className="w-4.5 h-4.5 text-[#60CDFF]" aria-hidden="true" />
            </div>
            <div>
              <h3 id="output-folder-title" className="font-sans font-semibold text-[15px] text-[#F3F3F3]">
                Output Folder (Local Disk)
              </h3>
              <p className="text-[12px] text-[#A6A6A6]">
                Files saved directly on this computer
              </p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="w-8 h-8 rounded-md hover:bg-white/5 flex items-center justify-center text-[#A6A6A6] hover:text-[#F3F3F3] cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none active:scale-90 active:translate-y-px transition-transform duration-100 ease-out"
            aria-label="Close"
            type="button"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>

        {/* Local Disk Location Banner & OS Actions */}
        <div className="px-5 py-3 bg-[#2D2D2D] border-b border-white/[0.04] flex flex-wrap items-center justify-between gap-3 shrink-0">
          <div className="flex items-center gap-2 flex-1 min-w-[280px]">
            <span className="text-[11.5px] font-semibold text-[#A6A6A6] uppercase tracking-wider shrink-0">
              Location:
            </span>
            <div className="flex items-center gap-1.5 bg-[#202020] px-2.5 py-1 rounded-md border border-white/[0.06] font-mono text-[11.5px] text-[#F3F3F3] truncate flex-1 shadow-xs">
              <span className="truncate">{effectiveFolderPath}</span>
              <button
                type="button"
                onClick={handleCopyFolderPath}
                className="text-[#A6A6A6] hover:text-[#F3F3F3] ml-1 p-0.5 rounded cursor-pointer active:scale-95 active:translate-y-px transition-all duration-100 ease-out focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
                title="Copy folder path"
                aria-label="Copy folder path"
              >
                {copiedPath ? (
                  <Check className="w-3.5 h-3.5 text-[#78c697]" />
                ) : (
                  <Copy className="w-3.5 h-3.5" />
                )}
              </button>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {explorerOpenedFeedback && (
              <span className="text-[11.5px] font-medium text-[#60CDFF] bg-[#60CDFF]/10 border border-[#60CDFF]/30 px-2 py-0.5 rounded-sm animate-fade-in">
                {explorerOpenedFeedback}
              </span>
            )}
            <button
              type="button"
              onClick={() => handleOpenInExplorer()}
              className="h-8 px-3.5 bg-[#60CDFF] hover:bg-[#4CC2FF] active:bg-[#0091E6] text-[#000000] font-semibold text-[12.5px] rounded-md shadow-xs active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out flex items-center gap-1.5 cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
              title="Open folder in Windows File Explorer (os.startfile)"
            >
              <ExternalLink className="w-3.5 h-3.5" aria-hidden="true" />
              <span>Open in File Explorer</span>
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="flex-1 flex overflow-hidden divide-x divide-white/[0.04] min-h-[320px]">
          {/* File list */}
          <div className="w-1/2 p-3 overflow-y-auto space-y-1.5 bg-[#272727]">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-[#A6A6A6] px-2 py-1 flex items-center justify-between">
              <span>Files on disk ({files.length})</span>
              <span className="font-mono text-[10.5px] text-[#A6A6A6] font-normal">DOCX · MD · JSON</span>
            </div>
            {files.length === 0 ? (
              <div className="p-8 text-center text-[13px] text-[#A6A6A6]">
                <FileText className="w-8 h-8 text-[#929292] mx-auto mb-2 opacity-50" />
                No exported files in output directory yet.
              </div>
            ) : (
              files.map((file) => {
                const isSelected = selectedFile?.id === file.id;
                const fullDiskPath = file.localPath || `${effectiveFolderPath}\\${file.filename}`;

                let badgeClass = 'bg-white/5 text-[#F3F3F3] border-white/[0.08]';
                if (file.type === 'docx') badgeClass = 'bg-[#60CDFF]/10 text-[#60CDFF] border-[#60CDFF]/30';
                if (file.type === 'md') badgeClass = 'bg-[#78c697]/10 text-[#78c697] border-[#78c697]/30';
                if (file.type === 'json') badgeClass = 'bg-white/5 text-[#F3F3F3] border-white/[0.08]';

                return (
                  <div
                    key={file.id}
                    role="button"
                    tabIndex={0}
                    aria-label={`Select file ${file.filename}`}
                    aria-pressed={isSelected}
                    onClick={() => {
                      setSelectedFile(file);
                      setDeleteConfirmId(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        setSelectedFile(file);
                        setDeleteConfirmId(null);
                      }
                    }}
                    className={`p-2.5 rounded-md flex items-center justify-between cursor-pointer text-[13px] transition-colors group focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none ${
                      isSelected
                        ? 'bg-[#60CDFF]/15 border border-[#60CDFF]/30 text-[#F3F3F3] font-medium shadow-xs'
                        : 'hover:bg-[#2D2D2D] text-[#A6A6A6] border border-transparent'
                    }`}
                  >
                    <div className="flex items-center gap-2 truncate">
                      <span className={`text-[10px] font-mono font-bold uppercase px-1.5 py-0.5 rounded-sm border ${badgeClass} shrink-0`}>
                        {file.type}
                      </span>
                      <div className="truncate">
                        <div className="truncate font-medium text-[#F3F3F3]">{file.filename}</div>
                        <div className="text-[11px] text-[#929292] font-mono">{file.size} · {file.timestamp}</div>
                      </div>
                    </div>

                    <div className="flex items-center gap-1 shrink-0 ml-2">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleOpenInExplorer(fullDiskPath);
                        }}
                        className="px-2 py-1 text-[11px] border border-white/[0.08] hover:border-[#60CDFF] hover:bg-white/5 text-[#A6A6A6] hover:text-[#60CDFF] rounded-md transition-colors cursor-pointer flex items-center gap-1 focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
                        title="Reveal file in Windows File Explorer"
                      >
                        <ExternalLink className="w-3 h-3" />
                        <span className="hidden sm:inline">Reveal</span>
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* File preview & Inspector */}
          <div className="w-1/2 p-4 flex flex-col overflow-hidden bg-[#202020]">
            {selectedFile ? (
              <>
                <div className="pb-3 border-b border-white/[0.04] mb-3">
                  <div className="flex items-center justify-between gap-2">
                    <h4 className="font-semibold text-[13.5px] text-[#F3F3F3] truncate" title={selectedFile.filename}>
                      {selectedFile.filename}
                    </h4>
                    <span className="text-[11px] font-mono px-2 py-0.5 rounded-sm bg-white/5 text-[#A6A6A6] shrink-0">
                      {selectedFile.size}
                    </span>
                  </div>
                  <div className="text-[11.5px] text-[#929292] font-mono truncate mt-0.5" title={selectedFile.localPath || `${effectiveFolderPath}\\${selectedFile.filename}`}>
                    {selectedFile.localPath || `${effectiveFolderPath}\\${selectedFile.filename}`}
                  </div>

                  <div className="flex items-center justify-between pt-2.5 mt-2 border-t border-white/[0.04]">
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => handleOpenInExplorer(selectedFile.localPath || `${effectiveFolderPath}\\${selectedFile.filename}`)}
                        className="px-2.5 py-1 text-[11.5px] bg-[#60CDFF]/10 hover:bg-[#60CDFF]/20 text-[#60CDFF] border border-[#60CDFF]/30 rounded-md font-medium flex items-center gap-1.5 cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
                        title="Reveal in Windows Explorer"
                      >
                        <ExternalLink className="w-3 h-3" />
                        <span>Reveal in Explorer</span>
                      </button>
                    </div>

                    {/* Delete with confirm step */}
                    {deleteConfirmId === selectedFile.id ? (
                      <div className="flex items-center gap-1 bg-red-500/10 p-0.5 rounded-md border border-red-500/30">
                        <span className="text-[11px] text-[#e58383] font-medium px-1">Delete this file?</span>
                        <button
                          type="button"
                          onClick={() => handleDeleteFile(selectedFile)}
                          className="px-2 py-0.5 bg-red-600 hover:bg-red-700 text-white rounded-md text-[11px] font-medium cursor-pointer focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none"
                        >
                          Yes
                        </button>
                        <button
                          type="button"
                          onClick={() => setDeleteConfirmId(null)}
                          className="px-2 py-0.5 border border-white/[0.08] bg-[#2D2D2D] text-[#F3F3F3] rounded-md text-[11px] font-medium cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setDeleteConfirmId(selectedFile.id)}
                        className="p-1 text-[#A6A6A6] hover:text-[#e58383] rounded-md hover:bg-red-500/10 cursor-pointer focus-visible:ring-2 focus-visible:ring-red-600 focus-visible:outline-none"
                        title="Delete file"
                        aria-label="Delete file"
                        type="button"
                      >
                        <Trash2 className="w-4 h-4" aria-hidden="true" />
                      </button>
                    )}
                  </div>
                </div>

                {/* File Contents Preview */}
                <div className="flex-1 overflow-auto bg-[#181818] p-3 rounded-md border border-white/[0.04] font-mono text-[12px] text-[#F3F3F3] leading-relaxed whitespace-pre-wrap selection:bg-[#60CDFF]/20">
                  {selectedFile.type === 'docx' ? (
                    <div className="text-[#A6A6A6]">
                      <div className="p-2 mb-2 rounded-md bg-[#60CDFF]/10 border border-[#60CDFF]/20 text-[#60CDFF] text-[11.5px] font-sans">
                        ℹ Microsoft Word OpenXML (.docx) binary package on disk. Structured text content extracted below:
                      </div>
                      {selectedFile.content}
                    </div>
                  ) : (
                    selectedFile.content
                  )}
                </div>
              </>
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center text-[#A6A6A6] text-[13px]">
                <Eye className="w-8 h-8 mb-1 text-[#929292]" aria-hidden="true" />
                <span>Select a file to inspect</span>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-white/[0.04] bg-[#272727] flex justify-between items-center text-[12px] text-[#A6A6A6]">
          <span>Destination managed by AksaraSight Engine (OCR_OUTPUT_DIR)</span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-md border border-white/[0.08] hover:border-white/[0.16] bg-[#2D2D2D] text-[#F3F3F3] font-medium hover:bg-white/[0.04] cursor-pointer focus-visible:ring-2 focus-visible:ring-[#60CDFF] focus-visible:outline-none"
            type="button"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
