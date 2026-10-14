import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { OutputFolderModal } from '../components/OutputFolderModal';
import App from '../App';
import { ExportedFile } from '../types';

const mockFiles: ExportedFile[] = [
  {
    id: 'out-1',
    filename: 'test-doc.md',
    type: 'md',
    timestamp: '2026-10-14 12:00',
    size: '1.2 KB',
    localPath: 'C:\\Users\\Fradana\\Documents\\AksaraSight\\output\\test-doc.md',
    content: '# Extracted Title\nBody text content',
  },
  {
    id: 'out-2',
    filename: 'test-table.json',
    type: 'json',
    timestamp: '2026-10-14 12:05',
    size: '3.4 KB',
    localPath: 'C:\\Users\\Fradana\\Documents\\AksaraSight\\output\\test-table.json',
    content: '{"data": "table"}',
  },
];

describe('OutputFolderModal Component and Live Backend Integration', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('renders files and folder path, and verifies Spike Slice Notice is NOT in the document', () => {
    const customPath = 'C:\\Custom\\Output\\Path';
    render(
      <OutputFolderModal
        isOpen={true}
        onClose={vi.fn()}
        files={mockFiles}
        onDeleteFile={vi.fn()}
        folderPath={customPath}
      />
    );

    expect(screen.getByText(customPath)).toBeInTheDocument();
    expect(screen.getAllByText('test-doc.md').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('test-table.json')).toBeInTheDocument();

    // Verify Spike Slice Notice banner is completely removed
    expect(screen.queryByText(/Spike Slice Notice/i)).toBeNull();
  });

  it('clicking "Open in File Explorer" triggers POST /api/output/open with empty path', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ opened: true, target: 'C:\\Custom\\Output\\Path' }),
    });
    global.fetch = fetchMock;

    render(
      <OutputFolderModal
        isOpen={true}
        onClose={vi.fn()}
        files={mockFiles}
        onDeleteFile={vi.fn()}
        folderPath="C:\\Custom\\Output\\Path"
      />
    );

    const openBtn = screen.getByRole('button', { name: /Open in File Explorer/i });
    await user.click(openBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/output/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
    });

    expect(await screen.findByText('Opened in File Explorer')).toBeInTheDocument();
  });

  it('clicking "Reveal in Explorer" triggers POST /api/output/open with specific file path', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ opened: true, target: mockFiles[0].localPath }),
    });
    global.fetch = fetchMock;

    render(
      <OutputFolderModal
        isOpen={true}
        onClose={vi.fn()}
        files={mockFiles}
        onDeleteFile={vi.fn()}
        folderPath="C:\\Custom\\Output\\Path"
      />
    );

    const revealBtn = screen.getByRole('button', { name: /Reveal in Explorer/i });
    await user.click(revealBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/output/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: mockFiles[0].localPath }),
      });
    });

    expect(await screen.findByText('Revealed in File Explorer')).toBeInTheDocument();
  });

  it('deleting a file triggers DELETE /api/output/{filename} and calls onDeleteFile', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ deleted: true, filename: 'test-doc.md' }),
    });
    global.fetch = fetchMock;
    const onDeleteFile = vi.fn();

    render(
      <OutputFolderModal
        isOpen={true}
        onClose={vi.fn()}
        files={mockFiles}
        onDeleteFile={onDeleteFile}
        folderPath="C:\\Custom\\Output\\Path"
      />
    );

    // Click delete icon button
    const deleteBtn = screen.getByRole('button', { name: /Delete file/i });
    await user.click(deleteBtn);

    // Confirmation appears
    expect(screen.getByText('Delete this file?')).toBeInTheDocument();
    const confirmBtn = screen.getByRole('button', { name: /^Yes$/i });
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/output/test-doc.md', {
        method: 'DELETE',
      });
    });

    expect(onDeleteFile).toHaveBeenCalledWith('out-1');
  });

  it('App rehydrates output files from GET /api/output and renders them in OutputFolderModal', async () => {
    class MockEventSource {
      addEventListener = vi.fn();
      removeEventListener = vi.fn();
      close = vi.fn();
    }
    const originalEventSource = global.EventSource;
    global.EventSource = MockEventSource as any;

    const user = userEvent.setup();
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/output')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            path: 'C:\\Users\\Fradana\\Documents\\AksaraSight\\output',
            files: mockFiles,
          }),
        });
      }
      if (url.includes('/health')) {
        return Promise.resolve({ ok: true, json: async () => ({ status: 'running' }) });
      }
      if (url.includes('/api/documents')) {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      if (url.includes('/api/server/status')) {
        return Promise.resolve({ ok: true, json: async () => ({ status: 'ready', ownership: 'managed' }) });
      }
      if (url.includes('/api/model/status')) {
        return Promise.resolve({ ok: true, json: async () => ({ downloaded: true }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });
    global.fetch = fetchMock;

    try {
      render(<App />);

      // Open OutputFolderModal from TopNavBar button
      const openOutputBtn = await screen.findByRole('button', { name: /Output Folder/i });
      await user.click(openOutputBtn);

      // Verify modal is open and shows live files
      expect(await screen.findByText('test-table.json')).toBeInTheDocument();
      expect(screen.getByText('C:\\Users\\Fradana\\Documents\\AksaraSight\\output')).toBeInTheDocument();
    } finally {
      global.EventSource = originalEventSource;
    }
  });
});

