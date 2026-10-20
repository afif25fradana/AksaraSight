import React, { useState, useRef, useMemo, useEffect } from 'react';
import { flushSync } from 'react-dom';
import { TopNavBar } from './components/TopNavBar';
import { FileQueuePanel } from './components/FileQueuePanel';
import { DocumentPreviewPanel } from './components/DocumentPreviewPanel';
import { ExtractedTextPanel } from './components/ExtractedTextPanel';
import { SettingsView } from './components/SettingsView';
import { OutputFolderModal } from './components/OutputFolderModal';
import { ServerLogsModal } from './components/ServerLogsModal';
import { DocumentItem, EngineSettings, ExportedFile, ModelStatusInfo, OutputFormatType, PromptMode, ServerStatusInfo } from './types';
import { INITIAL_DOCUMENTS, INITIAL_SETTINGS } from './data/mockDocuments';

export default function App() {
  const [currentTab, setCurrentTab] = useState<'workspace' | 'settings'>('workspace');

  // Theme state with localStorage persistence
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    if (typeof document !== 'undefined' && document.documentElement.classList.contains('dark')) {
      return 'dark';
    }
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('aksarasight_theme');
      if (stored === 'light' || stored === 'dark') return stored;
      if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        return 'dark';
      }
    }
    return 'light';
  });

  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('aksarasight_theme', theme);
      if (theme === 'dark') {
        document.documentElement.classList.add('dark');
      } else {
        document.documentElement.classList.remove('dark');
      }
    }
  }, [theme]);

  // Preview states driven via URL query param (?state=offline | ?state=empty | ?state=processing)
  const urlState = useMemo(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      return params.get('state');
    }
    return null;
  }, []);

  const [documents, setDocuments] = useState<DocumentItem[]>(() => {
    if (urlState === 'demo') return INITIAL_DOCUMENTS;
    if (urlState === 'processing') {
      return INITIAL_DOCUMENTS.map((d) =>
        d.id === 'doc-2' ? { ...d, status: 'Processing' as const, processedPages: 3 } : d
      );
    }
    return [];
  });

  const [selectedDocId, setSelectedDocId] = useState<string | null>(() => {
    if (urlState === 'demo') return 'doc-2';
    return null;
  });

  const [selectedDpi, setSelectedDpi] = useState<number>(100);

  const documentsRef = useRef(documents);
  documentsRef.current = documents;

  useEffect(() => {
    if (selectedDocId !== null && !documents.some((d) => d.id === selectedDocId)) {
      setSelectedDocId(documents.length > 0 ? documents[0].id : null);
    }
  }, [documents, selectedDocId]);

  useEffect(() => {
    return () => {
      documentsRef.current.forEach((d) => {
        if (d.previewImageUrl && d.previewImageUrl.startsWith('blob:')) {
          URL.revokeObjectURL(d.previewImageUrl);
        }
      });
    };
  }, []);

  const [engineSettings, setEngineSettings] = useState<EngineSettings>(() => {
    if (urlState === 'offline') {
      return { ...INITIAL_SETTINGS, status: 'offline' };
    }
    return INITIAL_SETTINGS;
  });

  const [isOutputFolderOpen, setIsOutputFolderOpen] = useState(false);
  const [isServerLogsOpen, setIsServerLogsOpen] = useState(false);

  // Track which document owns the running job
  const [runningJobDocId, setRunningJobDocId] = useState<string | null>(null);

  // Server management status and transitioning state
  const [serverStatus, setServerStatus] = useState<ServerStatusInfo | null>(null);
  const [isServerTransitioning, setIsServerTransitioning] = useState<boolean>(false);

  const fetchServerStatus = async () => {
    try {
      const res = await fetch('/api/server/status');
      if (res.ok) {
        const data: ServerStatusInfo = await res.json();
        if (data && data.status) {
          const normalizedStatus = String(data.status).toLowerCase() as 'offline' | 'starting' | 'ready' | 'error';
          const normalizedOwnership = String(data.ownership || 'none').toLowerCase() as 'none' | 'managed' | 'external';
          const normalized: ServerStatusInfo = {
            ...data,
            status: normalizedStatus,
            ownership: normalizedOwnership,
          };
          setServerStatus(normalized);
          setEngineSettings((prev) => ({
            ...prev,
            status: normalizedStatus === 'ready' ? 'running' : 'offline',
          }));
        }
      }
    } catch (err) {
      console.error('Failed to fetch server status:', err);
    }
  };

  useEffect(() => {
    fetchServerStatus();
    const interval = setInterval(fetchServerStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  // Model weights status state and actions
  const [modelStatus, setModelStatus] = useState<ModelStatusInfo | null>(null);

  const fetchModelStatus = async () => {
    try {
      const res = await fetch('/api/model/status');
      if (res.ok) {
        const data: ModelStatusInfo = await res.json();
        setModelStatus(data);
      }
    } catch (err) {
      console.error('Failed to fetch model status:', err);
    }
  };

  useEffect(() => {
    fetchModelStatus();
  }, []);

  const handleDownloadModel = async () => {
    try {
      setModelStatus((prev) => (prev ? { ...prev, is_downloading: true, error: null } : null));
      const res = await fetch('/api/model/download', { method: 'POST' });
      if (res.ok) {
        await fetchModelStatus();
      } else {
        const body = await res.json().catch(() => ({}));
        setModelStatus((prev) =>
          prev
            ? { ...prev, is_downloading: false, error: body.detail || 'Failed to start model download' }
            : null
        );
      }
    } catch (err) {
      console.error('Failed to start model download:', err);
      setModelStatus((prev) =>
        prev ? { ...prev, is_downloading: false, error: 'Network error starting download' } : null
      );
    }
  };

  const handleCancelModelDownload = async () => {
    try {
      const res = await fetch('/api/model/download/cancel', { method: 'POST' });
      if (res.ok) {
        await fetchModelStatus();
      }
    } catch (err) {
      console.error('Failed to cancel model download:', err);
    }
  };

  // Real Server-Sent Events (SSE) listener and loopback health probe
  useEffect(() => {
    const rehydrateDocuments = async () => {
      try {
        const res = await fetch('/api/documents');
        if (res.ok) {
          const serverDocs: DocumentItem[] = await res.json();
          if (serverDocs && serverDocs.length > 0) {
            setDocuments((prevDocs) => {
              if (!serverDocs || serverDocs.length === 0) return prevDocs;
              return serverDocs.map((sDoc) => {
                const existing = prevDocs.find((d) => d.id === sDoc.id);
                if (!existing) return sDoc;

                if (existing.runId && sDoc.runId && existing.runId !== sDoc.runId) {
                  return sDoc;
                }

                const mergedPagesData = { ...(sDoc.pagesData || {}), ...(existing.pagesData || {}) };
                const sortedKeys = Object.keys(mergedPagesData).map(Number).sort((a, b) => a - b);
                const fullText = sortedKeys.map((k) => mergedPagesData[k]?.text || '').join('\n\n---\n\n');

                const existingPagesCount = Object.keys(existing.pagesData || {}).length;
                const serverPagesCount = Object.keys(sDoc.pagesData || {}).length;

                const processedPages = Math.max(existing.processedPages || 0, sDoc.processedPages || 0);
                const isCurrentlyProcessing =
                  (existing.status === 'Processing' || sDoc.status === 'Processing') && sDoc.status !== 'Done';

                return {
                  ...sDoc,
                  status: isCurrentlyProcessing ? 'Processing' : (existing.status === 'Done' ? 'Done' : sDoc.status),
                  processedPages: processedPages,
                  pagesData: mergedPagesData,
                  extractedText:
                    (existingPagesCount > serverPagesCount ? existing.extractedText : fullText) || sDoc.extractedText,
                };
              });
            });
            setSelectedDocId((prev) => {
              if (prev && serverDocs.some((d) => d.id === prev)) return prev;
              return serverDocs[0].id;
            });
            const running = serverDocs.find((d) => d.status === 'Processing');
            if (running) {
              setRunningJobDocId(running.id);
            }
          }
        }
      } catch (err) {
        console.error('Failed to rehydrate documents from server:', err);
      }
    };

    rehydrateDocuments();

    const eventSource = new EventSource('/api/events');

    if (typeof window !== 'undefined') {
      (window as any).__eventSource = eventSource;
      (window as any).__rehydrateDocuments = rehydrateDocuments;
    }

    eventSource.onopen = () => {
      rehydrateDocuments();
    };

    eventSource.onerror = (err) => {
      console.warn('SSE connection interrupted, keeping local state:', err);
    };

    eventSource.addEventListener('queued', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setDocuments((prev) =>
          prev.map((doc) =>
            doc.id === data.job_id
              ? { ...doc, status: 'Waiting', statusNote: 'Queued for processing' }
              : doc
          )
        );
      } catch (err) {
        console.error('Error handling queued event', err);
      }
    });

    eventSource.addEventListener('started', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setRunningJobDocId(data.job_id);
        setDocuments((prev) =>
          prev.map((doc) =>
            doc.id === data.job_id
              ? {
                  ...doc,
                  status: 'Processing',
                  processedPages: 0,
                  pagesData: {},
                  extractedText: '',
                  runId: data.run_id,
                  statusNote: undefined,
                }
              : doc
          )
        );
      } catch (err) {
        console.error('Error handling started event', err);
      }
    });

    eventSource.addEventListener('page_progress', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setDocuments((prev) =>
          prev.map((doc) => {
            if (doc.id === data.job_id) {
              const updatedPagesData = { ...(doc.pagesData || {}) };
              updatedPagesData[data.page_number] = {
                pageNumber: data.page_number,
                text: data.text,
                latency: data.latency,
                tokens: data.tokens,
                isTruncated: data.truncated,
              };

              const sortedKeys = Object.keys(updatedPagesData)
                .map(Number)
                .sort((a, b) => a - b);
              const fullText = sortedKeys
                .map((k) => updatedPagesData[k]?.text || '')
                .join('\n\n---\n\n');

              return {
                ...doc,
                processedPages: data.page_number,
                pagesData: updatedPagesData,
                extractedText: fullText,
              };
            }
            return doc;
          })
        );
      } catch (err) {
        console.error('Error handling page_progress event', err);
      }
    });

    eventSource.addEventListener('completed', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setRunningJobDocId((curr) => (curr === data.job_id ? null : curr));
        setDocuments((prev) =>
          prev.map((doc) => {
            if (doc.id === data.job_id) {
              return {
                ...doc,
                status: 'Done',
                processedPages: data.total_pages || doc.pages,
                statusNote: undefined,
              };
            }
            return doc;
          })
        );
      } catch (err) {
        console.error('Error handling completed event', err);
      }
    });

    eventSource.addEventListener('cancelled', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setRunningJobDocId((curr) => (curr === data.job_id ? null : curr));
        setDocuments((prev) =>
          prev.map((doc) =>
            doc.id === data.job_id
              ? { ...doc, status: 'Waiting', statusNote: 'Job cancelled' }
              : doc
          )
        );
      } catch (err) {
        console.error('Error handling cancelled event', err);
      }
    });

    eventSource.addEventListener('failed', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setRunningJobDocId((curr) => (curr === data.job_id ? null : curr));
        setDocuments((prev) =>
          prev.map((doc) =>
            doc.id === data.job_id
              ? { ...doc, status: 'Failed', statusNote: data.error || 'Failed' }
              : doc
          )
        );
      } catch (err) {
        console.error('Error handling failed event', err);
      }
    });

    eventSource.addEventListener('model_download_progress', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setModelStatus((prev) =>
          prev
            ? {
                ...prev,
                is_downloading: data.is_downloading ?? true,
                bytes_downloaded: data.bytes_downloaded ?? prev.bytes_downloaded,
                percent: data.percent ?? prev.percent,
                active_file: data.active_file ?? prev.active_file,
                downloaded: data.status === 'completed' ? true : prev.downloaded,
                error: data.error ?? null,
              }
            : null
        );
        if (data.status === 'completed') {
          fetchModelStatus();
        }
      } catch (err) {
        console.warn('Failed to parse model download SSE event:', err);
      }
    });

    return () => {
      eventSource.close();
      if (typeof window !== 'undefined') {
        delete (window as any).__eventSource;
        delete (window as any).__rehydrateDocuments;
      }
    };
  }, []);

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
      console.error('Failed to fetch output files:', err);
    }
  };

  useEffect(() => {
    fetchOutputFiles();
  }, []);

  useEffect(() => {
    if (isOutputFolderOpen) {
      fetchOutputFiles();
    }
  }, [isOutputFolderOpen]);

  // Dynamic status consistency check
  const consistentDocuments = documents.map((doc) => {
    const hasText = Boolean(doc.extractedText && doc.extractedText.trim().length > 0);
    
    // Cannot be Done without extracted text
    if (doc.status === 'Done' && !hasText) {
      return { ...doc, status: 'Waiting' as const };
    }

    // Only runningJobDocId can be in Processing state
    if (doc.status === 'Processing' && doc.id !== runningJobDocId) {
      return { ...doc, status: 'Waiting' as const, statusNote: doc.statusNote || 'Queued' };
    }

    // When offline, unprocessed file must be Waiting or Not extracted
    if (engineSettings.status === 'offline') {
      if (doc.status === 'Processing') {
        return { ...doc, status: 'Waiting' as const, statusNote: 'Engine offline' };
      }
      if (!hasText && doc.status !== 'Failed' && doc.status !== 'Truncated') {
        return { ...doc, status: 'Not extracted' as const };
      }
    }

    return doc;
  });

  const selectedDocument = consistentDocuments.find((d) => d.id === selectedDocId) || null;

  // Add uploaded files to queue via POST /api/documents
  const handleAddFiles = async (files: FileList | File[]) => {
    const fileList = Array.from(files);
    for (const file of fileList) {
      const formData = new FormData();
      formData.append('file', file);
      try {
        const res = await fetch('/api/documents', {
          method: 'POST',
          body: formData,
        });
        if (res.ok) {
          const data = await res.json();
          const docId = data.id || data.job_id;
          const pageCount = data.pages || data.total_pages || 1;
          const newItem: DocumentItem = {
            id: docId,
            name: data.filename,
            pages: pageCount,
            processedPages: 0,
            size: `${(file.size / (1024 * 1024)).toFixed(1)} MB`,
            status: 'Not extracted',
            statusNote: 'Ready to extract',
            currentPage: 1,
            docType: 'custom-image',
            previewImageUrl: data.preview_url || `/api/documents/${docId}/pages/1/preview`,
            extractedText: '',
            pagesData: {},
          };
          setDocuments((prev) => [...prev, newItem]);
          setSelectedDocId(docId);
        } else {
          const errData = await res.json().catch(() => ({}));
          const errorMsg = errData.detail || errData.error || errData.message || `Upload failed (HTTP ${res.status})`;
          console.error('Upload failed with status', res.status, errorMsg);
          alert(errorMsg);
        }
      } catch (err: any) {
        console.error('Failed to upload file', err);
        alert(err?.message || 'Failed to upload file');
      }
    }
  };

  // Selective Clear Finished: Purges completed (Done) or failed (Failed) items and cleans up blob URLs
  const handleClearFinished = () => {
    const toRemove = documents.filter((d) => d.status === 'Done' || d.status === 'Failed');
    toRemove.forEach((d) => {
      if (d.previewImageUrl && d.previewImageUrl.startsWith('blob:')) {
        URL.revokeObjectURL(d.previewImageUrl);
      }
      fetch(`/api/documents/${d.id}`, { method: 'DELETE' }).catch((err) => {
        console.error(`Failed to delete finished document ${d.id} from backend:`, err);
      });
    });

    setDocuments((prev) => prev.filter((d) => d.status !== 'Done' && d.status !== 'Failed'));
  };

  const handlePageChange = (newPage: number) => {
    if (!selectedDocId) return;
    setDocuments((prev) =>
      prev.map((doc) =>
        doc.id === selectedDocId
          ? {
              ...doc,
              currentPage: newPage,
              previewImageUrl: `/api/documents/${doc.id}/pages/${newPage}/preview`,
            }
          : doc
      )
    );
  };

  // Run whole document extraction via POST /api/documents/{id}/extract
  const handleRunDocumentExtraction = async (docId: string, promptMode?: PromptMode, dpi?: number) => {
    if (serverStatus?.status !== 'ready' && engineSettings.status !== 'running') return;

    const isBusy = runningJobDocId !== null;
    if (!isBusy) {
      setRunningJobDocId(docId);
    }

    const mode = promptMode || (selectedDocument?.id === docId ? (selectedDocument.promptMode || 'text') : 'text');
    const extractDpi = dpi || selectedDpi || 100;

    setDocuments((prev) =>
      prev.map((doc) =>
        doc.id === docId
          ? isBusy
            ? { ...doc, status: 'Waiting', statusNote: 'Queued for processing', promptMode: mode }
            : { ...doc, status: 'Processing', processedPages: 0, statusNote: undefined, promptMode: mode }
          : doc
      )
    );

    try {
      const res = await fetch(`/api/documents/${docId}/extract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt_mode: mode, dpi: extractDpi }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        const errorMsg = errData.detail || errData.error || errData.message || 'Extraction failed';
        setRunningJobDocId((curr) => (curr === docId ? null : curr));
        setDocuments((prev) =>
          prev.map((doc) =>
            doc.id === docId
              ? { ...doc, status: 'Failed', statusNote: errorMsg }
              : doc
          )
        );
      }
    } catch (err: any) {
      console.error('Failed to start document extraction:', err);
      setRunningJobDocId((curr) => (curr === docId ? null : curr));
      setDocuments((prev) =>
        prev.map((doc) =>
          doc.id === docId
            ? { ...doc, status: 'Failed', statusNote: err?.message || 'Failed to start extraction' }
            : doc
        )
      );
    }
  };

  const handleAddToQueue = (docId: string) => {
    handleRunDocumentExtraction(docId);
  };

  const handleRemoveFromQueue = (docId: string) => {
    setDocuments((prev) => {
      const updated = prev.map((doc) => {
        if (doc.id === docId) {
          if (doc.isReExtractionQueued) {
            return {
              ...doc,
              isReExtractionQueued: false,
              queuePosition: undefined,
            };
          }
          if (doc.status === 'Waiting') {
            return {
              ...doc,
              status: 'Not extracted' as const,
              statusNote: 'Not extracted',
              queuePosition: undefined,
            };
          }
        }
        return doc;
      });

      let nextPos = 1;
      return updated.map((doc) => {
        if (doc.id !== docId && doc.status === 'Waiting') {
          const pos = nextPos++;
          return {
            ...doc,
            queuePosition: pos,
            statusNote: `Queued #${pos}`,
          };
        }
        if (doc.id !== docId && doc.isReExtractionQueued) {
          const pos = nextPos++;
          return {
            ...doc,
            queuePosition: pos,
          };
        }
        return doc;
      });
    });
  };

  const handleCancelExtraction = async (docId: string) => {
    try {
      await fetch(`/api/documents/${docId}/cancel`, { method: 'POST' });
    } catch (err) {
      console.error('Failed to cancel extraction:', err);
    }
    setRunningJobDocId(null);

    setDocuments((prev) =>
      prev.map((doc) =>
        doc.id === docId
          ? {
              ...doc,
              status: 'Waiting' as const,
              statusNote: 'Job cancelled',
              queuePosition: undefined,
            }
          : doc
      )
    );
  };

  const handleReExtractDocument = (docId: string, promptMode?: PromptMode, dpi?: number) => {
    if (runningJobDocId !== null) {
      setDocuments((prev) => {
        const currentQueued = prev.filter((d) => d.status === 'Waiting' || d.isReExtractionQueued);
        const nextPos = currentQueued.length + 1;
        return prev.map((doc) =>
          doc.id === docId
            ? {
                ...doc,
                isReExtractionQueued: true,
                queuePosition: nextPos,
                ...(promptMode ? { promptMode } : {}),
              }
            : doc
        );
      });
    } else {
      handleRunDocumentExtraction(docId, promptMode, dpi);
    }
  };

  const handleRetryDoc = (docId: string) => {
    handleRunDocumentExtraction(docId);
  };

  const handleRemoveDoc = (docId: string) => {
    fetch(`/api/documents/${docId}`, { method: 'DELETE' }).catch((err) => {
      console.error('Failed to delete document from backend:', err);
    });

    setDocuments((prev) => {
      const docToRemove = prev.find((d) => d.id === docId);
      if (docToRemove?.previewImageUrl && docToRemove.previewImageUrl.startsWith('blob:')) {
        URL.revokeObjectURL(docToRemove.previewImageUrl);
      }
      return prev.filter((doc) => doc.id !== docId);
    });
  };

  // Export handler matching engine formats: docx, md, json, both
  const handleExport = (format: OutputFormatType) => {
    if (!selectedDocument) return;

    const baseName = selectedDocument.name.replace(/\.[^/.]+$/, '');

    const triggerDownload = (ext: 'docx' | 'md' | 'json') => {
      const downloadUrl = `/api/documents/${selectedDocument.id}/export?format=${ext}`;
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.setAttribute('download', `${baseName}.${ext}`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
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

  const handleDeleteExportFile = (id: string) => {
    setExportedFiles((prev) => prev.filter((f) => f.id !== id));
  };

  const handleToggleServer = async () => {
    if (isServerTransitioning) return;
    const isRunning = serverStatus
      ? String(serverStatus.status).toLowerCase() === 'ready'
      : engineSettings.status === 'running';
    if (isRunning) {
      if (String(serverStatus?.ownership || '').toLowerCase() === 'external' || runningJobDocId !== null) return;
    }
    setIsServerTransitioning(true);
    try {
      if (isRunning) {
        const res = await fetch('/api/server/stop', { method: 'POST' });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          const errorMsg = errData.detail || errData.error || errData.message || `Failed to stop server (HTTP ${res.status})`;
          alert(errorMsg);
        }
      } else {
        const res = await fetch('/api/server/start', { method: 'POST' });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          const errorMsg = errData.detail || errData.error || errData.message || `Failed to start server (HTTP ${res.status})`;
          alert(errorMsg);
        }
      }
      await fetchServerStatus();
    } catch (err: any) {
      console.error('Failed to toggle server state:', err);
      alert(err?.message || 'Failed to toggle server state');
    } finally {
      setIsServerTransitioning(false);
    }
  };

  const handleToggleTheme = (event?: React.SyntheticEvent) => {
    const nextTheme = theme === 'light' ? 'dark' : 'light';

    if (
      typeof document !== 'undefined' &&
      'startViewTransition' in document &&
      !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ) {
      let x = window.innerWidth - 32;
      let y = 24;

      if (event?.target && (event.target as HTMLElement).getBoundingClientRect) {
        const rect = (event.target as HTMLElement).getBoundingClientRect();
        x = rect.left + rect.width / 2;
        y = rect.top + rect.height / 2;
      }

      const endRadius = Math.hypot(
        Math.max(x, window.innerWidth - x),
        Math.max(y, window.innerHeight - y)
      );

      document.documentElement.style.setProperty('--ripple-x', `${x}px`);
      document.documentElement.style.setProperty('--ripple-y', `${y}px`);
      document.documentElement.style.setProperty('--ripple-r', `${endRadius}px`);

      (document as any).startViewTransition(() => {
        if (nextTheme === 'dark') {
          document.documentElement.classList.add('dark');
        } else {
          document.documentElement.classList.remove('dark');
        }
        localStorage.setItem('aksarasight_theme', nextTheme);
        flushSync(() => {
          setTheme(nextTheme);
        });
      });
    } else {
      if (nextTheme === 'dark') {
        document.documentElement.classList.add('dark');
      } else {
        document.documentElement.classList.remove('dark');
      }
      localStorage.setItem('aksarasight_theme', nextTheme);
      setTheme(nextTheme);
    }
  };

  return (
    <div className="bg-[#EFEDE6] dark:bg-[var(--bg-base)] text-[#14213D] dark:text-[var(--text-1)] antialiased h-screen overflow-hidden flex flex-col font-sans text-[13px] select-text relative transition-colors">
      {/* Top Application Bar with Server Controls, Theme & Logs */}
      <TopNavBar
        currentTab={currentTab}
        onSelectTab={setCurrentTab}
        engineSettings={engineSettings}
        onToggleServer={handleToggleServer}
        onOpenServerLogs={() => setIsServerLogsOpen(true)}
        onOpenOutputFolder={() => setIsOutputFolderOpen(true)}
        theme={theme}
        onToggleTheme={handleToggleTheme}
        serverStatus={serverStatus}
        isExtracting={runningJobDocId !== null}
        isTransitioning={isServerTransitioning}
      />

      {/* Main Workspace 3-Pane Layout */}
      {currentTab === 'workspace' ? (
        <div className="flex-1 p-3 pb-2.5 min-h-0 overflow-hidden relative z-10 animate-fade-in">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-3 h-full min-h-0">
            <div className="lg:col-span-3 h-full min-h-0 overflow-hidden">
              <FileQueuePanel
                documents={consistentDocuments}
                selectedDocId={selectedDocId}
                onSelectDoc={setSelectedDocId}
                onAddFiles={handleAddFiles}
                onClearFinished={handleClearFinished}
                onOpenSettings={() => setCurrentTab('settings')}
                onRetryDoc={handleRetryDoc}
                onRemoveDoc={handleRemoveDoc}
                onRemoveFromQueue={handleRemoveFromQueue}
              />
            </div>

            <div className="lg:col-span-5 h-full min-h-0 overflow-hidden">
              <DocumentPreviewPanel
                document={selectedDocument}
                onPageChange={handlePageChange}
              />
            </div>

            <div className="lg:col-span-4 h-full min-h-0 overflow-hidden">
              <ExtractedTextPanel
                document={selectedDocument}
                runningJobDocId={runningJobDocId}
                isEngineOnline={serverStatus ? String(serverStatus.status).toLowerCase() === 'ready' : engineSettings.status === 'running'}
                isTransitioning={isServerTransitioning}
                selectedDpi={selectedDpi}
                onDpiChange={setSelectedDpi}
                onStartEngine={handleToggleServer}
                onOpenSettings={() => setCurrentTab('settings')}
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
      ) : (
        /* Settings Tab View */
        <div className="relative z-10 flex-1 min-h-0 overflow-hidden flex flex-col animate-fade-in">
          <SettingsView
            settings={engineSettings}
            onSave={(newSettings) => {
              setEngineSettings((prev) => ({
                ...prev,
                ...newSettings,
              }));
            }}
            onCancel={() => setCurrentTab('workspace')}
            modelStatus={modelStatus}
            onDownloadModel={handleDownloadModel}
            onCancelModelDownload={handleCancelModelDownload}
          />
        </div>
      )}

      {/* Output Directory Modal */}
      <OutputFolderModal
        isOpen={isOutputFolderOpen}
        onClose={() => setIsOutputFolderOpen(false)}
        files={exportedFiles}
        onDeleteFile={handleDeleteExportFile}
        folderPath={outputFolderPath}
      />

      {/* Server Logs Modal */}
      <ServerLogsModal
        isOpen={isServerLogsOpen}
        onClose={() => setIsServerLogsOpen(false)}
        serverStatus={serverStatus}
      />
    </div>
  );
}
