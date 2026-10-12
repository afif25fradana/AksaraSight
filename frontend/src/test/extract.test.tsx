import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';
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
