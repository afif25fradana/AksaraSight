import React, { useState } from 'react';
import { FolderOpen, X, Trash2, Eye, ExternalLink, Copy, Check, FileText } from 'lucide-react';
import { ExportedFile } from '../types';

interface OutputFolderModalProps {
  isOpen: boolean;
  onClose: () => void;
  files: ExportedFile[];
  onDeleteFile: (id: string) => void;
}

const LOCAL_OUTPUT_PATH = 'C:\\Users\\Fradana\\Documents\\AksaraSight\\output';

export const OutputFolderModal: React.FC<OutputFolderModalProps> = ({
  isOpen,
  onClose,
  files,
  onDeleteFile,
}) => {
  const [selectedFile, setSelectedFile] = useState<ExportedFile | null>(files[0] || null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [copiedPath, setCopiedPath] = useState(false);
  const [explorerOpenedFeedback, setExplorerOpenedFeedback] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleCopyFolderPath = () => {
    navigator.clipboard.writeText(LOCAL_OUTPUT_PATH);
    setCopiedPath(true);
    setTimeout(() => setCopiedPath(false), 2000);
  };

  const handleOpenInExplorer = (filePath?: string) => {
    const feedbackText = filePath
      ? `Revealed ${filePath.split('\\').pop() || ''} in File Explorer`
      : 'Opened in File Explorer';
    setExplorerOpenedFeedback(feedbackText);
    setTimeout(() => setExplorerOpenedFeedback(null), 3000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#14213D]/40 dark:bg-black/70 backdrop-blur-[4px] animate-modal-backdrop">
      <div 
        className="w-full max-w-3xl bg-white dark:bg-[var(--bg-surface)] rounded-xl shadow-[0_20px_50px_rgba(20,33,61,0.25)] dark:shadow-[0_20px_50px_rgba(0,0,0,0.6)] border border-[#14213D]/15 dark:border-[var(--border)] animate-modal-window will-change-transform overflow-hidden flex flex-col max-h-[88vh] text-[#14213D] dark:text-[var(--text-1)] transition-colors"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="output-folder-title"
      >
        {/* Modal Header */}
        <div className="px-5 py-4 border-b border-[#8A94A6]/25 dark:border-[var(--border)] flex items-center justify-between bg-[#F8F7F3] dark:bg-[var(--bg-surface)]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-[#0F766E]/10 dark:bg-[var(--accent)]/10 flex items-center justify-center text-[#0F766E] dark:text-[var(--accent)]">
              <FolderOpen className="w-4.5 h-4.5 text-[#0F766E] dark:text-[var(--accent)]" aria-hidden="true" />
            </div>
            <div>
              <h3 id="output-folder-title" className="font-['IBM_Plex_Sans',sans-serif] font-semibold text-[15px] text-[#14213D] dark:text-[var(--text-1)]">
                Output Folder (Local Disk)
              </h3>
              <p className="text-[12px] text-[#5A6478] dark:text-[var(--text-2)]">
                Files saved directly on this computer
              </p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="w-8 h-8 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 flex items-center justify-center text-[#5A6478] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)] cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none active:scale-90 active:translate-y-px transition-transform duration-100 ease-out"
            aria-label="Close"
            type="button"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>

        {/* Local Disk Location Banner & OS Actions */}
        <div className="px-5 py-3 bg-[#F0EEE8] dark:bg-[var(--bg-elevated)] border-b border-[#8A94A6]/25 dark:border-[var(--border)] flex flex-wrap items-center justify-between gap-3 shrink-0">
          <div className="flex items-center gap-2 flex-1 min-w-[280px]">
            <span className="text-[11.5px] font-semibold text-[#5A6478] dark:text-[var(--text-2)] uppercase tracking-wider shrink-0">
              Location:
            </span>
            <div className="flex items-center gap-1.5 bg-white dark:bg-[var(--bg-base)] px-2.5 py-1 rounded-md border border-[#8A94A6]/30 dark:border-[var(--border)] font-mono text-[11.5px] text-[#14213D] dark:text-[var(--text-1)] truncate flex-1 shadow-2xs">
              <span className="truncate">{LOCAL_OUTPUT_PATH}</span>
              <button
                type="button"
                onClick={handleCopyFolderPath}
                className="text-[#5A6478] dark:text-[var(--text-2)] hover:text-[#14213D] dark:hover:text-[var(--text-1)] ml-1 p-0.5 rounded cursor-pointer active:scale-95 active:translate-y-px transition-all duration-100 ease-out"
                title="Copy folder path"
                aria-label="Copy folder path"
              >
                {copiedPath ? (
                  <Check className="w-3.5 h-3.5 text-emerald-600 dark:text-[var(--success)]" />
                ) : (
                  <Copy className="w-3.5 h-3.5" />
                )}
              </button>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {explorerOpenedFeedback && (
              <span className="text-[11.5px] font-medium text-[#0F766E] dark:text-[var(--accent)] bg-teal-50 dark:bg-[var(--accent)]/10 border border-teal-200 dark:border-[var(--accent)]/30 px-2 py-0.5 rounded animate-fade-in">
                {explorerOpenedFeedback}
              </span>
            )}
            <button
              type="button"
              onClick={() => handleOpenInExplorer()}
              className="h-8 px-3.5 bg-[#0F766E] dark:bg-[var(--accent)] hover:bg-[#115E59] dark:hover:bg-[var(--accent)]/90 active:bg-[#0d4f4b] text-white dark:text-[var(--bg-base)] font-semibold text-[12.5px] rounded-lg shadow-xs active:scale-[0.96] active:translate-y-px transition-all duration-150 ease-out flex items-center gap-1.5 cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none"
              title="Open folder in Windows File Explorer (os.startfile)"
            >
              <ExternalLink className="w-3.5 h-3.5" aria-hidden="true" />
              <span>Open in File Explorer</span>
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="flex-1 flex overflow-hidden divide-x divide-[#8A94A6]/25 dark:divide-[var(--border)] min-h-[320px]">
          {/* File list */}
          <div className="w-1/2 p-3 overflow-y-auto space-y-1.5 bg-[#FCFBF8] dark:bg-[var(--bg-surface)]">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-[#5A6478] dark:text-[var(--text-2)] px-2 py-1 flex items-center justify-between">
              <span>Files on disk ({files.length})</span>
              <span className="font-mono text-[10.5px] text-[#5A6478] dark:text-[var(--text-2)] font-normal">DOCX · MD · JSON</span>
            </div>
            {files.length === 0 ? (
              <div className="p-8 text-center text-[13px] text-[#5A6478] dark:text-[var(--text-2)]">
                <FileText className="w-8 h-8 text-[#8A94A6] dark:text-[var(--text-3)] mx-auto mb-2 opacity-50" />
                No exported files in output directory yet.
              </div>
            ) : (
              files.map((file) => {
                const isSelected = selectedFile?.id === file.id;
                const fullDiskPath = file.localPath || `${LOCAL_OUTPUT_PATH}\\${file.filename}`;

                let badgeClass = 'bg-slate-100 dark:bg-[var(--bg-elevated)] text-slate-800 dark:text-[var(--text-1)] border-slate-200 dark:border-[var(--border)]';
                if (file.type === 'docx') badgeClass = 'bg-blue-50 dark:bg-[var(--accent)]/10 text-blue-800 dark:text-[var(--accent)] border-blue-200 dark:border-[var(--accent)]/30';
                if (file.type === 'md') badgeClass = 'bg-emerald-50 dark:bg-[var(--success)]/10 text-emerald-800 dark:text-[var(--success)] border-emerald-200 dark:border-[var(--success)]/30';
                if (file.type === 'json') badgeClass = 'bg-purple-50 dark:bg-[var(--accent-dim)]/15 text-purple-800 dark:text-[var(--accent)] border-purple-200 dark:border-[var(--accent)]/30';

                return (
                  <div
                    key={file.id}
                    onClick={() => {
                      setSelectedFile(file);
                      setDeleteConfirmId(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        setSelectedFile(file);
                        setDeleteConfirmId(null);
                      }
                    }}
                    tabIndex={0}
                    role="button"
                    className={`p-2.5 rounded-lg flex items-center justify-between cursor-pointer text-[13px] transition-colors group focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none ${
                      isSelected
                        ? 'bg-[#0F766E]/10 dark:bg-[var(--accent)]/15 border border-[#0F766E]/30 dark:border-[var(--accent)]/40 text-[#14213D] dark:text-[var(--text-1)] font-medium shadow-2xs'
                        : 'hover:bg-black/[0.03] dark:hover:bg-[var(--bg-elevated)] text-[#374151] dark:text-[var(--text-2)] border border-transparent'
                    }`}
                  >
                    <div className="flex items-center gap-2 truncate">
                      <span className={`text-[10px] font-mono font-bold uppercase px-1.5 py-0.5 rounded border ${badgeClass} shrink-0`}>
                        {file.type}
                      </span>
                      <div className="truncate">
                        <div className="truncate font-medium">{file.filename}</div>
                        <div className="text-[11px] text-[#5A6478] dark:text-[var(--text-2)] font-mono">{file.size} · {file.timestamp}</div>
                      </div>
                    </div>

                    <div className="flex items-center gap-1 shrink-0 ml-2">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleOpenInExplorer(fullDiskPath);
                        }}
                        className="px-2 py-1 text-[11px] border border-[#8A94A6]/40 dark:border-[var(--border)] hover:border-[#0F766E] dark:hover:border-[var(--accent)] hover:bg-white dark:hover:bg-[var(--bg-elevated)] text-[#4B5563] dark:text-[var(--text-2)] hover:text-[#0F766E] dark:hover:text-[var(--accent)] rounded transition-colors cursor-pointer flex items-center gap-1"
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
          <div className="w-1/2 p-4 flex flex-col overflow-hidden bg-white dark:bg-[var(--bg-surface)]">
            {selectedFile ? (
              <>
                <div className="pb-3 border-b border-[#8A94A6]/25 dark:border-[var(--border)] mb-3">
                  <div className="flex items-center justify-between gap-2">
                    <h4 className="font-semibold text-[13.5px] text-[#14213D] dark:text-[var(--text-1)] truncate" title={selectedFile.filename}>
                      {selectedFile.filename}
                    </h4>
                    <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-black/5 dark:bg-[var(--bg-elevated)] text-[#5A6478] dark:text-[var(--text-2)] shrink-0">
                      {selectedFile.size}
                    </span>
                  </div>
                  <div className="text-[11.5px] text-[#5A6478] dark:text-[var(--text-2)] font-mono truncate mt-0.5" title={selectedFile.localPath || `${LOCAL_OUTPUT_PATH}\\${selectedFile.filename}`}>
                    {selectedFile.localPath || `${LOCAL_OUTPUT_PATH}\\${selectedFile.filename}`}
                  </div>

                  <div className="flex items-center justify-between pt-2.5 mt-2 border-t border-black/5 dark:border-[var(--border)]">
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => handleOpenInExplorer(selectedFile.localPath || `${LOCAL_OUTPUT_PATH}\\${selectedFile.filename}`)}
                        className="px-2.5 py-1 text-[11.5px] bg-[#0F766E]/10 dark:bg-[var(--accent)]/10 hover:bg-[#0F766E]/15 dark:hover:bg-[var(--accent)]/20 text-[#0F766E] dark:text-[var(--accent)] border border-[#0F766E]/30 dark:border-[var(--accent)]/30 rounded-md font-medium flex items-center gap-1.5 cursor-pointer"
                        title="Reveal in Windows Explorer"
                      >
                        <ExternalLink className="w-3 h-3" />
                        <span>Reveal in Explorer</span>
                      </button>
                    </div>

                    {/* Delete with confirm step */}
                    {deleteConfirmId === selectedFile.id ? (
                      <div className="flex items-center gap-1 bg-red-50 dark:bg-[var(--danger)]/10 p-0.5 rounded border border-red-200 dark:border-[var(--danger)]/30">
                        <span className="text-[11px] text-red-700 dark:text-[var(--danger)] font-medium px-1">Delete this file?</span>
                        <button
                          type="button"
                          onClick={() => {
                            onDeleteFile(selectedFile.id);
                            setDeleteConfirmId(null);
                            setSelectedFile(null);
                          }}
                          className="px-2 py-0.5 bg-red-700 hover:bg-red-800 text-white rounded text-[11px] font-medium cursor-pointer"
                        >
                          Yes
                        </button>
                        <button
                          type="button"
                          onClick={() => setDeleteConfirmId(null)}
                          className="px-2 py-0.5 border border-[#8A94A6] dark:border-[var(--border)] bg-white dark:bg-[var(--bg-elevated)] text-[#374151] dark:text-[var(--text-1)] rounded text-[11px] font-medium cursor-pointer"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setDeleteConfirmId(selectedFile.id)}
                        className="p-1 text-[#5A6478] dark:text-[var(--text-2)] hover:text-red-700 dark:hover:text-[var(--danger)] rounded-md hover:bg-red-50 dark:hover:bg-[var(--danger)]/10 cursor-pointer"
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
                <div className="flex-1 overflow-auto bg-[#FAF9F5] dark:bg-[var(--bg-base)] p-3 rounded-lg border border-[#8A94A6]/30 dark:border-[var(--border)] font-mono text-[12px] text-[#14213D] dark:text-[var(--text-1)] leading-relaxed whitespace-pre-wrap selection:bg-[#0F766E]/20 dark:selection:bg-[var(--accent)]/20">
                  {selectedFile.type === 'docx' ? (
                    <div className="text-[#374151] dark:text-[var(--text-2)]">
                      <div className="p-2 mb-2 rounded bg-blue-50 dark:bg-[var(--accent)]/10 border border-blue-200 dark:border-[var(--accent)]/30 text-blue-900 dark:text-[var(--accent)] text-[11.5px] font-sans">
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
              <div className="flex-1 flex flex-col items-center justify-center text-[#5A6478] dark:text-[var(--text-2)] text-[13px]">
                <Eye className="w-8 h-8 mb-1 text-[#5A6478] dark:text-[var(--text-2)]" aria-hidden="true" />
                <span>Select a file to inspect</span>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-[#8A94A6]/25 dark:border-[var(--border)] bg-[#F8F7F3] dark:bg-[var(--bg-surface)] flex justify-between items-center text-[12px] text-[#5A6478] dark:text-[var(--text-2)]">
          <span>Destination managed by AksaraSight Engine (OCR_OUTPUT_DIR)</span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg border border-[#8A94A6] dark:border-[var(--border)] hover:border-[#14213D] dark:hover:border-[var(--border-strong)] bg-white dark:bg-[var(--bg-elevated)] text-[#14213D] dark:text-[var(--text-1)] font-medium hover:bg-black/[0.02] dark:hover:bg-[var(--bg-active)] cursor-pointer focus-visible:ring-2 focus-visible:ring-[#0F766E] focus-visible:outline-none"
            type="button"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
