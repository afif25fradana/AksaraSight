import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { NavRail, NavRailTab } from './components/workspace/NavRail';
import { TopNavBar } from './components/workspace/TopNavBar';
import { BottomStatusBar } from './components/workspace/BottomStatusBar';
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

const MemoizedFileQueuePanel = React.memo(FileQueuePanel);
const MemoizedDocumentPreviewPanel = React.memo(DocumentPreviewPanel);
const MemoizedExtractedTextPanel = React.memo(ExtractedTextPanel);

function AppContent() {
  const [currentTab, setCurrentTab] = useState<NavRailTab>('workspace');
  const [isQueueOpen, setIsQueueOpen] = useState<boolean>(true);
  const { toast } = useToastContext();

  const handleTabChange = useCallback((nextTab: NavRailTab) => {
    setCurrentTab(nextTab);
  }, []);

  const handleToggleQueue = useCallback(() => {
    if (currentTab !== 'workspace') {
      setCurrentTab('workspace');
      setIsQueueOpen(true);
    } else {
      setIsQueueOpen((prev) => !prev);
    }
  }, [currentTab]);

  const handleOpenSettings = useCallback(() => {
    handleTabChange('settings');
  }, [handleTabChange]);

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
    serverStatus, isTransitioning, handleToggleServer,
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

  const fetchOutputFiles = useCallback(async () => {
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
  }, []);

  useEffect(() => {
    fetchOutputFiles();
  }, [fetchOutputFiles]);

  useEffect(() => {
    if (isOutputFolderOpen) fetchOutputFiles();
  }, [isOutputFolderOpen, fetchOutputFiles]);

  // Export handler matching engine formats: docx, md, json, both
  const handleExport = useCallback((format: OutputFormatType) => {
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
  }, [selectedDocument, toast, fetchOutputFiles]);

  return (
    <div className="bg-[#202020] text-[#F3F3F3] antialiased h-screen overflow-hidden flex flex-row font-sans text-[14px] select-text relative">
      {/* 48px Left Navigation Rail */}
      <NavRail
        activeTab={currentTab}
        onSelectTab={handleTabChange}
        isQueueOpen={isQueueOpen}
        onToggleQueue={handleToggleQueue}
        onOpenServerLogs={() => setIsServerLogsOpen(true)}
      />

      {/* Main Column */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden">
        <TopNavBar
          onToggleServer={handleToggleServer}
          onOpenOutputFolder={() => setIsOutputFolderOpen(true)}
          serverStatus={serverStatus}
          isExtracting={runningJobDocId !== null}
          isTransitioning={isTransitioning}
        />

        <main
          id="main-content"
          tabIndex={-1}
          aria-label="AksaraSight Workspace"
          className="flex-1 min-h-0 flex flex-col overflow-hidden relative focus:outline-none"
        >
          {currentTab === 'settings' ? (
            <div
              role="tabpanel"
              id="nav-panel-settings"
              aria-labelledby="nav-tab-settings"
              tabIndex={0}
              className="relative z-10 flex-1 min-h-0 overflow-hidden flex flex-col animate-fade-in focus:outline-none"
            >
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
          ) : (
            <div
              role="tabpanel"
              id="nav-panel-workspace"
              aria-labelledby="nav-tab-workspace"
              tabIndex={0}
              className="flex-1 min-h-0 flex flex-col lg:flex-row p-2 gap-2 bg-[#202020] overflow-hidden relative z-10 focus:outline-none"
            >
              {isQueueOpen && (
                <aside
                  id="workspace-file-queue"
                  aria-label="Document Queue"
                  className="w-full lg:w-[252px] shrink-0 h-full bg-[#272727] rounded-lg border border-white/[0.04] overflow-hidden flex flex-col shadow-xs"
                >
                  <MemoizedFileQueuePanel
                    documents={documents}
                    selectedDocId={selectedDocId}
                    onSelectDoc={setSelectedDocId}
                    onAddFiles={handleAddFiles}
                    onClearFinished={handleClearFinished}
                    onOpenSettings={handleOpenSettings}
                    onRetryDoc={handleRetryDoc}
                    onRemoveDoc={handleRemoveDoc}
                    onRemoveFromQueue={handleRemoveFromQueue}
                  />
                </aside>
              )}

              <div className="flex-1 min-w-0 flex flex-col lg:flex-row gap-2 h-full overflow-hidden">
                <div className="flex-1 min-w-0 bg-[#272727] rounded-lg border border-white/[0.04] overflow-hidden flex flex-col shadow-xs">
                  <MemoizedDocumentPreviewPanel
                    document={selectedDocument}
                    onPageChange={handlePageChange}
                  />
                </div>
                <div className="flex-1 min-w-0 bg-[#272727] rounded-lg border border-white/[0.04] overflow-hidden flex flex-col shadow-xs">
                  <MemoizedExtractedTextPanel
                    document={selectedDocument}
                    runningJobDocId={runningJobDocId}
                    isEngineOnline={isEngineOnline}
                    isTransitioning={isTransitioning}
                    selectedDpi={selectedDpi}
                    onDpiChange={handleDpiChange}
                    onStartEngine={handleToggleServer}
                    onOpenSettings={handleOpenSettings}
                    onExport={handleExport}
                    onRunDocumentExtraction={handleRunDocumentExtraction}
                    onAddToQueue={handleAddToQueue}
                    onRemoveFromQueue={handleRemoveFromQueue}
                    onCancelExtraction={handleCancelExtraction}
                    onReExtractDocument={handleReExtractDocument}
                  />
                </div>
              </div>
            </div>
          )}
        </main>

        <BottomStatusBar
          serverStatus={serverStatus}
        />
      </div>

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
