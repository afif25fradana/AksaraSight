import { DocumentItem, DocumentStatus, SSECompletedEventData } from '../../types';

export function mergeRehydratedDocuments(
  prevDocs: DocumentItem[],
  serverDocs: DocumentItem[]
): DocumentItem[] {
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
}

export function computeConsistentDocuments(
  documents: DocumentItem[],
  runningJobDocId: string | null,
  isEngineOnline: boolean
): DocumentItem[] {
  return documents.map((doc) => {
    const hasText = Boolean(doc.extractedText && doc.extractedText.trim().length > 0);

    // Cannot be Done without extracted text UNLESS all pages were processed
    if (doc.status === 'Done' && !hasText && (doc.processedPages || 0) === 0) {
      return { ...doc, status: 'Waiting' as const };
    }

    // Only runningJobDocId can be in Processing state
    if (doc.status === 'Processing' && doc.id !== runningJobDocId) {
      return { ...doc, status: 'Waiting' as const, statusNote: doc.statusNote || 'Queued' };
    }

    // When offline, unprocessed file must be Waiting or Not extracted
    if (!isEngineOnline) {
      if (doc.status === 'Processing') {
        return { ...doc, status: 'Waiting' as const, statusNote: 'Engine offline' };
      }
      if (!hasText && doc.status !== 'Failed' && doc.status !== 'Truncated') {
        return { ...doc, status: 'Not extracted' as const };
      }
    }

    return doc;
  });
}

export function applyPageProgressToDocument(
  doc: DocumentItem,
  data: { page_number: number; text: string; latency?: number; tokens?: number; truncated?: boolean }
): DocumentItem {
  const updatedPagesData = { ...(doc.pagesData || {}) };
  updatedPagesData[data.page_number] = {
    pageNumber: data.page_number,
    text: data.text,
    latency: data.latency,
    tokens: data.tokens,
    isTruncated: data.truncated,
  };

  const sortedKeys = Object.keys(updatedPagesData).map(Number).sort((a, b) => a - b);
  const fullText = sortedKeys.map((k) => updatedPagesData[k]?.text || '').join('\n\n---\n\n');

  return {
    ...doc,
    processedPages: data.page_number,
    pagesData: updatedPagesData,
    extractedText: fullText,
  };
}

export function applyCompletedToDocument(
  doc: DocumentItem,
  data: SSECompletedEventData
): DocumentItem {
  const isTruncated =
    data.status === 'partial' ||
    data.truncated === true ||
    Object.values(doc.pagesData || {}).some((p) => p.isTruncated);

  return {
    ...doc,
    status: (isTruncated ? 'Truncated' : 'Done') as DocumentStatus,
    statusNote: isTruncated
      ? (data.status_note || doc.statusNote || 'Output truncated (hit token limit)')
      : undefined,
    processedPages: data.total_pages || doc.pages,
  };
}
