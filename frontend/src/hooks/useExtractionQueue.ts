import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { DocumentItem, PromptMode } from '../types';
import { INITIAL_DOCUMENTS } from '../data/mockDocuments';
import { useServerEvents } from '../context/ServerEventsContext';
import { useToast } from './useToast';
import {
  mergeRehydratedDocuments,
  computeConsistentDocuments,
} from './helpers/queueRehydration';
import {
  uploadDocumentFile,
  cancelDocumentExtraction,
  cleanupAndRemoveFinishedDocuments,
} from './helpers/queueApi';
import { useExtractionSSE } from './helpers/queueSSE';

export function useExtractionQueue(
  urlState: string | null,
  isEngineOnline: boolean,
  selectedDpi: number
) {
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

  const [runningJobDocId, setRunningJobDocId] = useState<string | null>(null);
  const [cancellingDocId, setCancellingDocId] = useState<string | null>(null);

  const { subscribe, isConnected } = useServerEvents();
  const { toast } = useToast();
  const documentsRef = useRef(documents);
  documentsRef.current = documents;
  const wasConnectedRef = useRef(false);

  // Cleanup blob URLs on unmount
  useEffect(() => {
    return () => {
      documentsRef.current.forEach((d) => {
        if (d.previewImageUrl && d.previewImageUrl.startsWith('blob:')) {
          URL.revokeObjectURL(d.previewImageUrl);
        }
      });
    };
  }, []);

  // Ensure selectedDocId remains valid
  useEffect(() => {
    if (selectedDocId !== null && !documents.some((d) => d.id === selectedDocId)) {
      setSelectedDocId(documents.length > 0 ? documents[0].id : null);
    }
  }, [documents, selectedDocId]);

  // Rehydrate documents from GET /api/documents
  const rehydrateDocuments = useCallback(async () => {
    try {
      const res = await fetch('/api/documents');
      if (res.ok) {
        const serverDocs: DocumentItem[] = await res.json();
        if (serverDocs && serverDocs.length > 0) {
          setDocuments((prevDocs) => mergeRehydratedDocuments(prevDocs, serverDocs));

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
      console.warn('Failed to rehydrate documents from server:', err);
    }
  }, []);

  useEffect(() => {
    rehydrateDocuments();
  }, [rehydrateDocuments]);

  // Re-trigger rehydrateDocuments on SSE reconnect
  useEffect(() => {
    if (isConnected && !wasConnectedRef.current) {
      rehydrateDocuments();
    }
    wasConnectedRef.current = isConnected;
  }, [isConnected, rehydrateDocuments]);

  // Subscribe to SSE extraction events
  useExtractionSSE({
    subscribe,
    setDocuments,
    setRunningJobDocId,
  });

  // Dynamic status consistency check
  const consistentDocuments = useMemo(() => {
    return computeConsistentDocuments(documents, runningJobDocId, isEngineOnline);
  }, [documents, runningJobDocId, isEngineOnline]);

  const selectedDocument = useMemo(() => {
    return consistentDocuments.find((d) => d.id === selectedDocId) || null;
  }, [consistentDocuments, selectedDocId]);

  // Ingest files via POST /api/documents
  const handleAddFiles = useCallback(async (files: FileList | File[]) => {
    const fileList = Array.from(files);
    for (const file of fileList) {
      const { docItem, error } = await uploadDocumentFile(file);
      if (docItem) {
        setDocuments((prev) => [...prev, docItem]);
        setSelectedDocId(docItem.id);
      } else if (error) {
        toast.error(error);
      }
    }
  }, [toast]);

  // Selective Clear Finished
  const handleClearFinished = useCallback(() => {
    setDocuments((prev) => cleanupAndRemoveFinishedDocuments(prev));
  }, []);

  const handlePageChange = useCallback((newPage: number) => {
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
  }, [selectedDocId]);

  // Run extraction via POST /api/documents/{id}/extract
  const handleRunDocumentExtraction = useCallback(async (
    docId: string,
    promptMode?: PromptMode,
    dpi?: number
  ) => {
    if (!isEngineOnline) return;

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
      const res = await fetch(`/api/documents/${encodeURIComponent(docId)}/extract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt_mode: mode, dpi: extractDpi }),
      });

      if (!res.ok) {
        let errorMsg = `Server error (HTTP ${res.status})`;
        try {
          const errData = await res.json();
          errorMsg = errData.detail || errData.error || errorMsg;
        } catch {
          // Response body may not be JSON
        }

        if (!isBusy) {
          setRunningJobDocId(null);
        }

        setDocuments((prev) =>
          prev.map((doc) =>
            doc.id === docId
              ? { ...doc, status: 'Failed', statusNote: errorMsg }
              : doc
          )
        );
        toast.error(errorMsg);
      }
    } catch (err: any) {
      if (!isBusy) {
        setRunningJobDocId(null);
      }
      const msg = err?.message || 'Network error: Failed to reach extraction server';
      setDocuments((prev) =>
        prev.map((doc) =>
          doc.id === docId
            ? { ...doc, status: 'Failed', statusNote: msg }
            : doc
        )
      );
      toast.error(msg);
    }
  }, [isEngineOnline, runningJobDocId, selectedDocument, selectedDpi, toast]);

  const handleAddToQueue = useCallback((docId: string) => {
    handleRunDocumentExtraction(docId);
  }, [handleRunDocumentExtraction]);

  const handleRemoveFromQueue = useCallback(async (docId: string) => {
    try {
      const res = await fetch(`/api/documents/${encodeURIComponent(docId)}/cancel`, {
        method: 'POST',
      });
      if (res.ok) {
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
              return {
                ...doc,
                status: 'Not extracted' as const,
                statusNote: 'Not extracted',
                queuePosition: undefined,
              };
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
      }
    } catch (err) {
      console.error('Failed to cancel queued document on server:', err);
    }
  }, []);

  // Cancel extraction via POST /api/documents/{id}/cancel
  const handleCancelExtraction = useCallback(async (docId: string) => {
    if (cancellingDocId === docId) return;
    setCancellingDocId(docId);

    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    const signal = controller?.signal;

    let timeoutId: any = null;
    let timedOut = false;
    if (controller) {
      timeoutId = setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, 10000);
    }

    try {
      const result = await cancelDocumentExtraction(docId, signal);

      if (result.success) {
        setRunningJobDocId(null);
        setDocuments((prev) =>
          prev.map((doc) =>
            doc.id === docId
              ? { ...doc, status: 'Waiting' as const, statusNote: 'Job cancelled', queuePosition: undefined }
              : doc
          )
        );
        toast.info('Extraction cancelled');
      } else if (result.isNotFound) {
        setRunningJobDocId(null);
        setDocuments((prev) =>
          prev.map((doc) =>
            doc.id === docId
              ? { ...doc, status: 'Waiting' as const, statusNote: 'Job not found on server', queuePosition: undefined }
              : doc
          )
        );
        toast.warning(result.message || 'Job not found on server');
      } else if (result.isFinished) {
        toast.info(result.message || 'Document extraction already finished');
      } else {
        toast.error(result.message || 'Failed to cancel extraction');
      }
    } catch (err: any) {
      const isTimeout = err?.name === 'TimeoutError' || timedOut;
      const alertMsg = isTimeout
        ? 'Cancellation request timed out. The extraction may still be running.'
        : 'Network error: Could not reach server to cancel extraction. Extraction is still running.';
      toast.error(alertMsg);
    } finally {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      setCancellingDocId(null);
    }
  }, [cancellingDocId, toast]);

  const handleReExtractDocument = useCallback((docId: string, promptMode?: PromptMode, dpi?: number) => {
    handleRunDocumentExtraction(docId, promptMode, dpi);
  }, [handleRunDocumentExtraction]);

  const handleRetryDoc = useCallback((docId: string) => {
    handleRunDocumentExtraction(docId);
  }, [handleRunDocumentExtraction]);

  const handleRemoveDoc = useCallback((docId: string) => {
    const doc = documents.find((d) => d.id === docId);
    if (doc?.previewImageUrl && doc.previewImageUrl.startsWith('blob:')) {
      URL.revokeObjectURL(doc.previewImageUrl);
    }
    fetch(`/api/documents/${docId}`, { method: 'DELETE' }).catch((err) => {
      console.error(`Failed to delete document ${docId} from backend:`, err);
    });
    setDocuments((prev) => prev.filter((d) => d.id !== docId));
    if (selectedDocId === docId) {
      const remaining = documents.filter((d) => d.id !== docId);
      setSelectedDocId(remaining.length > 0 ? remaining[0].id : null);
    }
  }, [documents, selectedDocId]);

  return {
    documents: consistentDocuments,
    selectedDocId,
    setSelectedDocId,
    selectedDocument,
    runningJobDocId,
    handleAddFiles,
    handleClearFinished,
    handlePageChange,
    handleRunDocumentExtraction,
    handleAddToQueue,
    handleRemoveFromQueue,
    handleCancelExtraction,
    handleReExtractDocument,
    handleRetryDoc,
    handleRemoveDoc,
    rehydrateDocuments,
  };
}
