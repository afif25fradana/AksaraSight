import React, { useState, useMemo, useEffect } from 'react';
import { flushSync } from 'react-dom';
import { TopNavBar } from './components/workspace/TopNavBar';
import { FileQueuePanel } from './components/workspace/FileQueuePanel';
import { DocumentPreviewPanel } from './components/workspace/DocumentPreviewPanel';
import { ExtractedTextPanel } from './components/workspace/ExtractedTextPanel';
import { SettingsView } from './components/settings/SettingsView';
import { OutputFolderModal } from './components/modals/OutputFolderModal';
import { ServerLogsModal } from './components/modals/ServerLogsModal';
import { ToastContainer } from './components/common/ToastContainer';
import { ServerEventsProvider } from './context/ServerEventsContext';
import { ToastProvider, useToastContext } from './context/ToastContext';
import { useServerStatus } from './hooks/useServerStatus';
import { useSettings } from './hooks/useSettings';
import { useExtractionQueue } from './hooks/useExtractionQueue';
import { ExportedFile, OutputFormatType } from './types';

function AppContent() {
  const [currentTab, setCurrentTab] = useState<'workspace' | 'settings'>('workspace');
  const { toast } = useToastContext();

  const handleTabChange = (nextTab: 'workspace' | 'settings') => {
    if (nextTab !== currentTab) setCurrentTab(nextTab);
  };

  // Theme state with localStorage persistence and View Transitions
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    if (typeof document !== 'undefined' && document.documentElement.classList.contains('dark')) return 'dark';
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('aksarasight_theme');
      if (stored === 'light' || stored === 'dark') return stored;
      if (window.matchMedia?.('(prefers-color-scheme: dark)').matches) return 'dark';
    }
    return 'light';
  });

  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('aksarasight_theme', theme);
      if (theme === 'dark') document.documentElement.classList.add('dark');
      else document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  const urlState = useMemo(() => {
    if (typeof window !== 'undefined') {
      return new URLSearchParams(window.location.search).get('state');
    }
    return null;
  }, []);

  // Domain Hooks
  const {
    selectedDpi, setSelectedDpi, engineSettings, setEngineSettings, modelStatus,
    handleDpiChange, handleSaveSettings, handleDownloadModel, handleCancelModelDownload,
  } = useSettings(urlState);

  const isEngineOnline = engineSettings.status === 'running';

  const {
    documents, selectedDocId, setSelectedDocId, selectedDocument, runningJobDocId,
    handleAddFiles, handleClearFinished, handlePageChange, handleRunDocumentExtraction,
    handleAddToQueue, handleRemoveFromQueue, handleCancelExtraction, handleReExtractDocument,
    handleRetryDoc, handleRemoveDoc,
  } = useExtractionQueue(urlState, isEngineOnline, selectedDpi);

  const {
    serverStatus, vram, isTransitioning, handleToggleServer,
  } = useServerStatus(runningJobDocId);

  // Sync engine settings running state from serverStatus
  useEffect(() => {
    if (serverStatus?.status) {
      const isReady = String(serverStatus.status).toLowerCase() === 'ready';
      setEngineSettings((prev) => {
        const nextStatus = isReady ? 'running' : 'offline';
        if (prev.status === nextStatus) return prev;
        return { ...prev, status: nextStatus };
      });
    }
  }, [serverStatus?.status, setEngineSettings]);

  // Output folder & logs modals
  const [isOutputFolderOpen, setIsOutputFolderOpen] = useState(false);
  const [isServerLogsOpen, setIsServerLogsOpen] = useState(false);
  const [exportedFiles, setExportedFiles] = useState<ExportedFile[]>([]);
  const [outputFolderPath, setOutputFolderPath] = useState<string>('~/Documents/AksaraSight/output');

  const fetchOutputFiles = async () => {
    try {
      const res = await fetch('/api/output');
      if (res.ok) {
        const data = await res.json();
        setExportedFiles(data.files || []);
        setOutputFolderPath(data.path || '');
      }
    } catch (err) {
      console.warn('Failed to fetch output files:', err);
    }
  };

  useEffect(() => {
    fetchOutputFiles();
  }, []);

  useEffect(() => {
    if (isOutputFolderOpen) fetchOutputFiles();
  }, [isOutputFolderOpen]);

  // Export handler matching engine formats: docx, md, json, both
  const handleExport = (format: OutputFormatType) => {
    if (!selectedDocument) return;
    const baseName = selectedDocument.name.replace(/\.[^/.]+$/, '');

    const triggerDownload = async (ext: 'docx' | 'md' | 'json') => {
      const downloadUrl = `/api/documents/${selectedDocument.id}/export?format=${ext}`;
      try {
        const res = await fetch(downloadUrl);
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          const errorMsg = errData.detail || errData.error || errData.message || `Export failed (HTTP ${res.status})`;
          toast.error(errorMsg);
          return;
        }
        const blob = await res.blob();
        const objectUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = objectUrl;
        link.setAttribute('download', `${baseName}.${ext}`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
        toast.success(`Exported ${baseName}.${ext}`);
      } catch (err: any) {
        console.error(`Failed to export document as ${ext}:`, err);
        toast.error(err?.message || `Failed to export document as ${ext}`);
      }
    };

    if (format === 'both') {
      triggerDownload('md');
      setTimeout(() => triggerDownload('json'), 300);
      fetchOutputFiles();
      setTimeout(fetchOutputFiles, 800);
    } else {
      triggerDownload(format);
      fetchOutputFiles();
      setTimeout(fetchOutputFiles, 800);
    }
  };

  const handleToggleTheme = (event?: React.SyntheticEvent) => {
    const nextTheme = theme === 'light' ? 'dark' : 'light';
    if (typeof document !== 'undefined' && 'startViewTransition' in document && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      let x = window.innerWidth - 32;
      let y = 24;
      if (event?.target && (event.target as HTMLElement).getBoundingClientRect) {
        const rect = (event.target as HTMLElement).getBoundingClientRect();
        x = rect.left + rect.width / 2;
        y = rect.top + rect.height / 2;
      }
      const endRadius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
      document.documentElement.style.setProperty('--ripple-x', `${x}px`);
      document.documentElement.style.setProperty('--ripple-y', `${y}px`);
      document.documentElement.style.setProperty('--ripple-r', `${endRadius}px`);

      (document as any).startViewTransition(() => {
        if (nextTheme === 'dark') document.documentElement.classList.add('dark');
        else document.documentElement.classList.remove('dark');
        localStorage.setItem('aksarasight_theme', nextTheme);
        flushSync(() => setTheme(nextTheme));
      });
    } else {
      if (nextTheme === 'dark') document.documentElement.classList.add('dark');
      else document.documentElement.classList.remove('dark');
      localStorage.setItem('aksarasight_theme', nextTheme);
      setTheme(nextTheme);
    }
  };

  return (
    <div className="bg-[#EFEDE6] dark:bg-[var(--bg-base)] text-[#14213D] dark:text-[var(--text-1)] antialiased h-screen overflow-hidden flex flex-col font-sans text-[13px] select-text relative transition-colors">
      <TopNavBar
        currentTab={currentTab}
        onSelectTab={handleTabChange}
        engineSettings={engineSettings}
        onToggleServer={handleToggleServer}
        onOpenServerLogs={() => setIsServerLogsOpen(true)}
        onOpenOutputFolder={() => setIsOutputFolderOpen(true)}
        theme={theme}
        onToggleTheme={handleToggleTheme}
        serverStatus={serverStatus}
        isExtracting={runningJobDocId !== null}
        isTransitioning={isTransitioning}
        vram={vram}
      />

      {currentTab === 'workspace' ? (
        <main className="flex-1 p-3 pb-2.5 min-h-0 overflow-y-auto lg:overflow-hidden relative z-10 animate-fade-in" aria-label="AksaraSight Workspace">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-3 lg:h-full min-h-0">
            <div className="lg:col-span-3 min-h-[340px] lg:min-h-0 lg:h-full overflow-hidden">
              <FileQueuePanel
                documents={documents}
                selectedDocId={selectedDocId}
                onSelectDoc={setSelectedDocId}
                onAddFiles={handleAddFiles}
                onClearFinished={handleClearFinished}
                onOpenSettings={() => handleTabChange('settings')}
                onRetryDoc={handleRetryDoc}
                onRemoveDoc={handleRemoveDoc}
                onRemoveFromQueue={handleRemoveFromQueue}
              />
            </div>

            <div className="lg:col-span-5 min-h-[460px] lg:min-h-0 lg:h-full overflow-hidden">
              <DocumentPreviewPanel
                document={selectedDocument}
                onPageChange={handlePageChange}
              />
            </div>

            <div className="lg:col-span-4 min-h-[460px] lg:min-h-0 lg:h-full overflow-hidden">
              <ExtractedTextPanel
                document={selectedDocument}
                runningJobDocId={runningJobDocId}
                isEngineOnline={isEngineOnline}
                isTransitioning={isTransitioning}
                selectedDpi={selectedDpi}
                onDpiChange={handleDpiChange}
                onStartEngine={handleToggleServer}
                onOpenSettings={() => handleTabChange('settings')}
                onExport={handleExport}
                onRunDocumentExtraction={handleRunDocumentExtraction}
                onAddToQueue={handleAddToQueue}
                onRemoveFromQueue={handleRemoveFromQueue}
                onCancelExtraction={handleCancelExtraction}
                onReExtractDocument={handleReExtractDocument}
              />
            </div>
          </div>
        </main>
      ) : (
        <div className="relative z-10 flex-1 min-h-0 overflow-hidden flex flex-col animate-fade-in">
          <SettingsView
            settings={engineSettings}
            onSave={(newSettings) => {
              handleSaveSettings(newSettings);
              if (typeof newSettings.dpi === 'number') setSelectedDpi(newSettings.dpi);
            }}
            onCancel={() => handleTabChange('workspace')}
            modelStatus={modelStatus}
            onDownloadModel={handleDownloadModel}
            onCancelModelDownload={handleCancelModelDownload}
          />
        </div>
      )}

      <OutputFolderModal
        isOpen={isOutputFolderOpen}
        onClose={() => setIsOutputFolderOpen(false)}
        files={exportedFiles}
        onDeleteFile={(id) => setExportedFiles((prev) => prev.filter((f) => f.id !== id))}
        folderPath={outputFolderPath}
      />

      <ServerLogsModal
        isOpen={isServerLogsOpen}
        onClose={() => setIsServerLogsOpen(false)}
        serverStatus={serverStatus}
      />

      <ToastContainer />
    </div>
  );
}

export default function App() {
  return (
    <ServerEventsProvider>
      <ToastProvider>
        <AppContent />
      </ToastProvider>
    </ServerEventsProvider>
  );
}
