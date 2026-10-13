import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';
import { ExtractedTextPanel } from '../components/ExtractedTextPanel';
import { DocumentItem } from '../types';

class MockEventSource {
  onopen: any = null;
  onerror: any = null;
  addEventListener = vi.fn();
  removeEventListener = vi.fn();
  close = vi.fn();
  constructor(public url: string) {}
}

describe('UI-to-API extraction wire contract (POST /api/documents/{id}/extract)', () => {
  const originalFetch = global.fetch;
  const originalEventSource = global.EventSource;

  beforeEach(() => {
    vi.restoreAllMocks();
    global.EventSource = MockEventSource as any;
  });

  afterEach(() => {
    global.fetch = originalFetch;
    global.EventSource = originalEventSource;
  });

  const mockDoc: DocumentItem = {
    id: 'doc-test-123',
    name: 'test-document.pdf',
    pages: 2,
    size: '1.2 MB',
    status: 'Not extracted',
    processedPages: 0,
    currentPage: 1,
    docType: 'invoice',
    extractedText: '',
  };

  it('sends POST /api/documents/{id}/extract with prompt_mode "table" when table preset is selected', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr === '/api/documents' && (!init || !init.method || init.method === 'GET')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => [mockDoc],
        } as Response);
      }
      if (urlStr === '/health') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'ok' }),
        } as Response);
      }
      if (urlStr.includes('/extract') && init?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ success: true }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      } as Response);
    });

    global.fetch = fetchMock;

    render(<App />);

    // Wait for document to load and Extract Document button to appear
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Extract Document' })).toBeInTheDocument();
    });

    // Select 'table' mode from task mode dropdown
    const modeDropdownButton = screen.getByTitle('GLM-OCR prompt task preset (--prompt-mode)');
    await user.click(modeDropdownButton);

    const tableOption = await screen.findByRole('menuitem', { name: /Table Recognition/i });
    await user.click(tableOption);

    // Click Extract Document button
    const extractButton = screen.getByRole('button', { name: 'Extract Document' });
    await user.click(extractButton);

    // Verify wire contract for POST /api/documents/{id}/extract
    await waitFor(() => {
      const extractCalls = fetchMock.mock.calls.filter(([url, init]) =>
        String(url).endsWith(`/api/documents/${mockDoc.id}/extract`) && init?.method === 'POST'
      );
      expect(extractCalls).toHaveLength(1);

      const [callUrl, callInit] = extractCalls[0];
      expect(callUrl).toBe(`/api/documents/${mockDoc.id}/extract`);
      expect(callInit?.method).toBe('POST');
      expect(callInit?.headers).toEqual({ 'Content-Type': 'application/json' });
      expect(callInit?.body).toBe(JSON.stringify({ prompt_mode: 'table' }));
    });
  });

  it('sends POST /api/documents/{id}/extract with default prompt_mode "text"', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr === '/api/documents' && (!init || !init.method || init.method === 'GET')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => [mockDoc],
        } as Response);
      }
      if (urlStr === '/health') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'ok' }),
        } as Response);
      }
      if (urlStr.includes('/extract') && init?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ success: true }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      } as Response);
    });

    global.fetch = fetchMock;

    render(<App />);

    // Wait for document to load and Extract Document button to appear
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Extract Document' })).toBeInTheDocument();
    });

    // Directly click Extract Document without changing mode (default is text)
    const extractButton = screen.getByRole('button', { name: 'Extract Document' });
    await user.click(extractButton);

    // Verify wire contract for POST /api/documents/{id}/extract with default 'text'
    await waitFor(() => {
      const extractCalls = fetchMock.mock.calls.filter(([url, init]) =>
        String(url).endsWith(`/api/documents/${mockDoc.id}/extract`) && init?.method === 'POST'
      );
      expect(extractCalls).toHaveLength(1);

      const [callUrl, callInit] = extractCalls[0];
      expect(callUrl).toBe(`/api/documents/${mockDoc.id}/extract`);
      expect(callInit?.method).toBe('POST');
      expect(callInit?.headers).toEqual({ 'Content-Type': 'application/json' });
      expect(callInit?.body).toBe(JSON.stringify({ prompt_mode: 'text' }));
    });
  });
});

describe('ExtractedTextPanel partial failure and total failure handling', () => {
  const defaultProps = {
    runningJobDocId: null,
    isEngineOnline: true,
    onStartEngine: vi.fn(),
    onOpenSettings: vi.fn(),
    onExport: vi.fn(),
    onRunDocumentExtraction: vi.fn(),
    onAddToQueue: vi.fn(),
    onRemoveFromQueue: vi.fn(),
    onCancelExtraction: vi.fn(),
    onReExtractDocument: vi.fn(),
  };

  it('renders incomplete extraction banner, partial text, retry, and export button for partial failure', () => {
    const partialDoc: DocumentItem = {
      id: 'doc-partial-1',
      name: 'multi-page-doc.pdf',
      pages: 2,
      size: '1.2 MB',
      status: 'Failed',
      statusNote: 'Engine out of memory on page 2',
      processedPages: 1,
      currentPage: 1,
      docType: 'invoice',
      extractedText: 'Partial page 1 content',
    };

    render(
      <ExtractedTextPanel
        {...defaultProps}
        document={partialDoc}
      />
    );

    // Renders the banner "Incomplete extraction"
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/Incomplete extraction:/i)).toBeInTheDocument();
    expect(screen.getByText(/Engine out of memory on page 2/i)).toBeInTheDocument();

    // Displays the extracted text
    expect(screen.getByText('Partial page 1 content')).toBeInTheDocument();

    // Renders "Retry extraction" button (in header) and "Retry" button (in banner)
    expect(screen.getByRole('button', { name: 'Retry extraction' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();

    // Renders the "Export" button
    expect(screen.getByRole('button', { name: /Export/i })).toBeInTheDocument();

    // Copy button is enabled
    expect(screen.getByRole('button', { name: 'Copy' })).not.toBeDisabled();
  });

  it('renders centered Extraction Failed card and Retry extraction button for total failure', () => {
    const totalFailDoc: DocumentItem = {
      id: 'doc-fail-1',
      name: 'corrupt-doc.pdf',
      pages: 1,
      size: '500 KB',
      status: 'Failed',
      statusNote: 'Image was too large to process',
      processedPages: 0,
      currentPage: 1,
      docType: 'invoice',
      extractedText: '',
    };

    render(
      <ExtractedTextPanel
        {...defaultProps}
        document={totalFailDoc}
      />
    );

    // Renders the centered "Extraction Failed" card
    expect(screen.getByText('Extraction Failed')).toBeInTheDocument();
    expect(screen.getByText('Image was too large to process')).toBeInTheDocument();

    // Renders Retry extraction button
    const retryButtons = screen.getAllByRole('button', { name: /Retry extraction/i });
    expect(retryButtons.length).toBeGreaterThanOrEqual(1);

    // Does NOT render incomplete extraction banner or Export button
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Export/i })).not.toBeInTheDocument();

    // Copy button is disabled
    expect(screen.getByRole('button', { name: 'Copy' })).toBeDisabled();
  });
});
