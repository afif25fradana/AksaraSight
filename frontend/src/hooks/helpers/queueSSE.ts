import { useEffect } from 'react';
import { DocumentItem, SSECompletedEventData } from '../../types';
import { applyCompletedToDocument, applyPageProgressToDocument } from './queueRehydration';

interface QueueSSEProps {
  subscribe: <T = any>(eventType: string, handler: (data: T, event: MessageEvent) => void) => () => void;
  setDocuments: React.Dispatch<React.SetStateAction<DocumentItem[]>>;
  setRunningJobDocId: React.Dispatch<React.SetStateAction<string | null>>;
}

export function useExtractionSSE({
  subscribe,
  setDocuments,
  setRunningJobDocId,
}: QueueSSEProps) {
  useEffect(() => {
    const unsubQueued = subscribe('queued', (data: any) => {
      setDocuments((prev) =>
        prev.map((doc) =>
          doc.id === data.job_id
            ? { ...doc, status: 'Waiting', statusNote: 'Queued for processing' }
            : doc
        )
      );
    });

    const unsubStarted = subscribe('started', (data: any) => {
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
    });

    const unsubProgress = subscribe('page_progress', (data: any) => {
      setDocuments((prev) =>
        prev.map((doc) =>
          doc.id === data.job_id ? applyPageProgressToDocument(doc, data) : doc
        )
      );
    });

    const unsubCompleted = subscribe('completed', (data: SSECompletedEventData) => {
      setRunningJobDocId((curr) => (curr === data.job_id ? null : curr));
      setDocuments((prev) =>
        prev.map((doc) =>
          doc.id === data.job_id ? applyCompletedToDocument(doc, data) : doc
        )
      );
    });

    const unsubCancelled = subscribe('cancelled', (data: any) => {
      setRunningJobDocId((curr) => (curr === data.job_id ? null : curr));
      setDocuments((prev) =>
        prev.map((doc) =>
          doc.id === data.job_id
            ? { ...doc, status: 'Waiting', statusNote: 'Job cancelled' }
            : doc
        )
      );
    });

    const unsubFailed = subscribe('failed', (data: any) => {
      setRunningJobDocId((curr) => (curr === data.job_id ? null : curr));
      setDocuments((prev) =>
        prev.map((doc) =>
          doc.id === data.job_id
            ? { ...doc, status: 'Failed', statusNote: data.error || 'Failed' }
            : doc
        )
      );
    });

    return () => {
      unsubQueued();
      unsubStarted();
      unsubProgress();
      unsubCompleted();
      unsubCancelled();
      unsubFailed();
    };
  }, [subscribe, setDocuments, setRunningJobDocId]);
}
