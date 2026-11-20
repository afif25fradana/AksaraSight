import { DocumentItem } from '../../types';

export async function uploadDocumentFile(file: File): Promise<{
  docItem?: DocumentItem;
  error?: string;
}> {
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
      return { docItem: newItem };
    } else {
      const errData = await res.json().catch(() => ({}));
      const errorMsg = errData.detail || errData.error || errData.message || `Upload failed (HTTP ${res.status})`;
      return { error: errorMsg };
    }
  } catch (err: any) {
    return { error: err?.message || 'Failed to upload file' };
  }
}

export async function cancelDocumentExtraction(
  docId: string,
  signal?: AbortSignal
): Promise<{
  success: boolean;
  status: number;
  message?: string;
  isNotFound?: boolean;
  isFinished?: boolean;
}> {
  const res = await fetch(`/api/documents/${encodeURIComponent(docId)}/cancel`, {
    method: 'POST',
    signal,
  });

  if (res.ok) {
    return { success: true, status: res.status };
  }

  let errorMsg = '';
  try {
    const errorJson = await res.json();
    errorMsg = errorJson?.detail || errorJson?.error || errorJson?.message || '';
  } catch {
    // Non-JSON response
  }

  if (res.status === 404) {
    return { success: false, status: 404, isNotFound: true, message: errorMsg || 'Job not found on server' };
  }
  if (res.status === 409) {
    return { success: false, status: 409, isFinished: true, message: errorMsg || 'Document extraction already finished' };
  }

  return {
    success: false,
    status: res.status,
    message: errorMsg ? `Failed to cancel extraction: ${errorMsg}` : `Failed to cancel extraction (server returned ${res.status})`,
  };
}

export function cleanupAndRemoveFinishedDocuments(documents: DocumentItem[]): DocumentItem[] {
  const toRemove = documents.filter((d) => d.status === 'Done' || d.status === 'Failed');
  toRemove.forEach((d) => {
    if (d.previewImageUrl && d.previewImageUrl.startsWith('blob:')) {
      URL.revokeObjectURL(d.previewImageUrl);
    }
    fetch(`/api/documents/${d.id}`, { method: 'DELETE' }).catch((err) => {
      console.error(`Failed to delete finished document ${d.id} from backend:`, err);
    });
  });

  return documents.filter((d) => d.status !== 'Done' && d.status !== 'Failed');
}
