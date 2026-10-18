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

  it('sends POST /api/documents/{id}/extract with prompt_mode "table" and dpi 100 when table preset is selected', async () => {
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
      if (urlStr === '/api/server/status') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'ready', ownership: 'managed' }),
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

    // Select 'table' mode from Extraction Options popover
    const optionsButton = screen.getByRole('button', { name: /Extraction Options/i });
    await user.click(optionsButton);

    const tableOption = await screen.findByRole('menuitem', { name: /Single Table Crop/i });
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
      expect(callInit?.body).toBe(JSON.stringify({ prompt_mode: 'table', dpi: 100 }));
    });
  });

  it('sends POST /api/documents/{id}/extract with default prompt_mode "text" and dpi 100', async () => {
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
      if (urlStr === '/api/server/status') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'ready', ownership: 'managed' }),
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

    // Directly click Extract Document without changing options (default is text, 100 DPI)
    const extractButton = screen.getByRole('button', { name: 'Extract Document' });
    await user.click(extractButton);

    // Verify wire contract for POST /api/documents/{id}/extract with default 'text' and dpi 100
    await waitFor(() => {
      const extractCalls = fetchMock.mock.calls.filter(([url, init]) =>
        String(url).endsWith(`/api/documents/${mockDoc.id}/extract`) && init?.method === 'POST'
      );
      expect(extractCalls).toHaveLength(1);

      const [callUrl, callInit] = extractCalls[0];
      expect(callUrl).toBe(`/api/documents/${mockDoc.id}/extract`);
      expect(callInit?.method).toBe('POST');
      expect(callInit?.headers).toEqual({ 'Content-Type': 'application/json' });
      expect(callInit?.body).toBe(JSON.stringify({ prompt_mode: 'text', dpi: 100 }));
    });
  });

  it('sends POST /api/documents/{id}/extract with dpi 150 when High Detail is selected in Extraction Options', async () => {
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
      if (urlStr === '/api/server/status') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'ready', ownership: 'managed' }),
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

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Extract Document' })).toBeInTheDocument();
    });

    // Open Extraction Options popover
    const optionsButton = screen.getByRole('button', { name: /Extraction Options/i });
    await user.click(optionsButton);

    // Verify popover sections exist
    expect(screen.getByText('EXTRACTION TARGET')).toBeInTheDocument();
    expect(screen.getByText('SCAN DETAIL / RESOLUTION')).toBeInTheDocument();

    // Select 150 DPI
    const highDetailOption = await screen.findByRole('menuitem', { name: /High Detail \(150 DPI\)/i });
    await user.click(highDetailOption);

    // Verify popover button label shows updated 150 DPI badge
    expect(optionsButton).toHaveTextContent('150 DPI');

    // Click Extract Document button
    const extractButton = screen.getByRole('button', { name: 'Extract Document' });
    await user.click(extractButton);

    // Verify wire contract includes dpi: 150
    await waitFor(() => {
      const extractCalls = fetchMock.mock.calls.filter(([url, init]) =>
        String(url).endsWith(`/api/documents/${mockDoc.id}/extract`) && init?.method === 'POST'
      );
      expect(extractCalls).toHaveLength(1);

      const [callUrl, callInit] = extractCalls[0];
      expect(callUrl).toBe(`/api/documents/${mockDoc.id}/extract`);
      expect(callInit?.method).toBe('POST');
      expect(callInit?.headers).toEqual({ 'Content-Type': 'application/json' });
      expect(callInit?.body).toBe(JSON.stringify({ prompt_mode: 'text', dpi: 150 }));
    });
  });

  it('enqueues document via POST /api/documents/{id}/extract when Add to Queue is clicked while another document is running', async () => {
    const user = userEvent.setup();
    const docRunning: DocumentItem = {
      id: 'doc-running-1',
      name: 'doc-running.pdf',
      pages: 1,
      size: '1.0 MB',
      status: 'Processing',
      processedPages: 0,
      currentPage: 1,
      docType: 'invoice',
      extractedText: '',
    };
    const docPending: DocumentItem = {
      id: 'doc-pending-2',
      name: 'doc-pending.pdf',
      pages: 1,
      size: '1.0 MB',
      status: 'Not extracted',
      processedPages: 0,
      currentPage: 1,
      docType: 'invoice',
      extractedText: '',
    };

    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr === '/api/documents' && (!init || !init.method || init.method === 'GET')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => [docRunning, docPending],
        } as Response);
      }
      if (urlStr === '/api/server/status') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'ready', ownership: 'managed' }),
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

    const pendingDocItem = await screen.findByText('doc-pending.pdf');
    await user.click(pendingDocItem);

    const addQueueButton = await screen.findByRole('button', { name: 'Add to Queue' });
    await user.click(addQueueButton);

    await waitFor(() => {
      const extractCalls = fetchMock.mock.calls.filter(([url, init]) =>
        String(url).endsWith('/api/documents/doc-pending-2/extract') && init?.method === 'POST'
      );
      expect(extractCalls).toHaveLength(1);
      const [callUrl, callInit] = extractCalls[0];
      expect(callUrl).toBe('/api/documents/doc-pending-2/extract');
      expect(callInit?.method).toBe('POST');
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

describe('ExtractedTextPanel Unified Extraction Options Popover', () => {
  const defaultProps = {
    runningJobDocId: null,
    isEngineOnline: true,
    selectedDpi: 100,
    onDpiChange: vi.fn(),
    onStartEngine: vi.fn(),
    onOpenSettings: vi.fn(),
    onExport: vi.fn(),
    onRunDocumentExtraction: vi.fn(),
    onAddToQueue: vi.fn(),
    onRemoveFromQueue: vi.fn(),
    onCancelExtraction: vi.fn(),
    onReExtractDocument: vi.fn(),
  };

  const sampleDoc: DocumentItem = {
    id: 'doc-options-1',
    name: 'sample.pdf',
    pages: 1,
    size: '100 KB',
    status: 'Not extracted',
    processedPages: 0,
    currentPage: 1,
    docType: 'invoice',
    extractedText: '',
  };

  it('renders Extraction Options button with mode and DPI badge, opens popover with both sections, and closes on Esc', async () => {
    const user = userEvent.setup();
    const onDpiChange = vi.fn();
    const onRunDocumentExtraction = vi.fn();

    render(
      <ExtractedTextPanel
        {...defaultProps}
        document={sampleDoc}
        selectedDpi={100}
        onDpiChange={onDpiChange}
        onRunDocumentExtraction={onRunDocumentExtraction}
      />
    );

    const toggleBtn = screen.getByRole('button', { name: /Extraction Options/i });
    expect(toggleBtn).toBeInTheDocument();
    expect(toggleBtn).toHaveTextContent('Full Document');
    expect(toggleBtn).toHaveTextContent('100 DPI');

    // Popover closed initially
    expect(screen.queryByRole('dialog', { name: /Extraction Options/i })).not.toBeInTheDocument();

    // Click to open
    await user.click(toggleBtn);
    expect(screen.getByRole('dialog', { name: /Extraction Options/i })).toBeInTheDocument();
    expect(screen.getByText('EXTRACTION TARGET')).toBeInTheDocument();
    expect(screen.getByText('SCAN DETAIL / RESOLUTION')).toBeInTheDocument();

    // Check target mode items
    expect(screen.getByText('Full Document (Text & Tables)')).toBeInTheDocument();
    expect(screen.getByText('Single Table Crop (Table Only)')).toBeInTheDocument();
    expect(screen.getByText('Math & Formulas')).toBeInTheDocument();

    // Check resolution items
    expect(screen.getByText('Standard (100 DPI)')).toBeInTheDocument();
    expect(screen.getByText('High Detail (150 DPI)')).toBeInTheDocument();
    expect(screen.getByText('Ultra Sharp (200 DPI)')).toBeInTheDocument();
    expect(screen.getByText('Recommended')).toBeInTheDocument();

    // Select 150 DPI
    const dpi150Option = screen.getByRole('menuitem', { name: /High Detail \(150 DPI\)/i });
    await user.click(dpi150Option);
    expect(onDpiChange).toHaveBeenCalledWith(150);

    // Select Single Table Crop
    const tableOption = screen.getByRole('menuitem', { name: /Single Table Crop/i });
    await user.click(tableOption);
    expect(toggleBtn).toHaveTextContent('Single Table Crop');

    // Press Escape to close popover
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: /Extraction Options/i })).not.toBeInTheDocument();

    // Click Extract Document and verify both taskMode and currentDpi are passed
    const extractBtn = screen.getByRole('button', { name: 'Extract Document' });
    await user.click(extractBtn);
    expect(onRunDocumentExtraction).toHaveBeenCalledWith('doc-options-1', 'table', 100);
  });
});

describe('ExtractedTextPanel engine start and queue wiring', () => {
  const defaultProps = {
    runningJobDocId: null,
    isEngineOnline: true,
    selectedDpi: 100,
    onDpiChange: vi.fn(),
    onStartEngine: vi.fn(),
    onOpenSettings: vi.fn(),
    onExport: vi.fn(),
    onRunDocumentExtraction: vi.fn(),
    onAddToQueue: vi.fn(),
    onRemoveFromQueue: vi.fn(),
    onCancelExtraction: vi.fn(),
    onReExtractDocument: vi.fn(),
  };

  const sampleDoc: DocumentItem = {
    id: 'doc-queue-test',
    name: 'test-queue.pdf',
    pages: 1,
    size: '200 KB',
    status: 'Not extracted',
    processedPages: 0,
    currentPage: 1,
    docType: 'invoice',
    extractedText: '',
  };

  it('verifies clicking "Start Engine" calls onStartEngine', async () => {
    const user = userEvent.setup();
    const onStartEngine = vi.fn();

    render(
      <ExtractedTextPanel
        {...defaultProps}
        document={sampleDoc}
        isEngineOnline={false}
        isTransitioning={false}
        onStartEngine={onStartEngine}
      />
    );

    const startBtn = screen.getByRole('button', { name: /Start Engine/i });
    expect(startBtn).toBeInTheDocument();
    await user.click(startBtn);
    expect(onStartEngine).toHaveBeenCalledTimes(1);
  });

  it('disables Start Engine button and displays Starting... with spinner when isTransitioning is true', () => {
    render(
      <ExtractedTextPanel
        {...defaultProps}
        document={sampleDoc}
        isEngineOnline={false}
        isTransitioning={true}
      />
    );

    const startBtn = screen.getByRole('button', { name: /Starting\.\.\./i });
    expect(startBtn).toBeInTheDocument();
    expect(startBtn).toBeDisabled();
  });

  it('verifies "Add to Queue" calls onRunDocumentExtraction', async () => {
    const user = userEvent.setup();
    const onRunDocumentExtraction = vi.fn();

    render(
      <ExtractedTextPanel
        {...defaultProps}
        document={sampleDoc}
        runningJobDocId="other-running-doc"
        isEngineOnline={true}
        onAddToQueue={onRunDocumentExtraction}
      />
    );

    const addToQueueBtn = screen.getByRole('button', { name: 'Add to Queue' });
    expect(addToQueueBtn).toBeInTheDocument();
    await user.click(addToQueueBtn);
    expect(onRunDocumentExtraction).toHaveBeenCalledWith('doc-queue-test');
  });
});

