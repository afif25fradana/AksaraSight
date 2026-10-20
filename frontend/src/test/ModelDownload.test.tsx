import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';
import { SettingsView } from '../components/SettingsView';
import { ModelStatusInfo } from '../types';

class MockEventSource {
  static instances: MockEventSource[] = [];
  listeners: Record<string, ((event: any) => void)[]> = {};
  onmessage: ((event: any) => void) | null = null;
  onopen: any = null;
  onerror: any = null;
  close = vi.fn();

  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: any) => void) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(listener);
  }

  removeEventListener(type: string, listener: (event: any) => void) {
    if (this.listeners[type]) {
      this.listeners[type] = this.listeners[type].filter((l) => l !== listener);
    }
  }

  emit(type: string, data: any) {
    const event = { data: typeof data === 'string' ? data : JSON.stringify(data) };
    if (this.listeners[type]) {
      this.listeners[type].forEach((l) => l(event));
    }
    if (type === 'message' && this.onmessage) {
      this.onmessage(event);
    }
  }
}

const mockDownloadedStatus: ModelStatusInfo = {
  repo: 'ggml-org/GLM-OCR-GGUF',
  revision: '65a42de',
  downloaded: true,
  model_path: 'C:\\Users\\TestUser\\AppData\\Local\\AksaraSight\\models\\glm-ocr-q8_0.gguf',
  mmproj_path: 'C:\\Users\\TestUser\\AppData\\Local\\AksaraSight\\models\\glm-ocr-mmproj.gguf',
  total_bytes: 1440000000,
  is_downloading: false,
  bytes_downloaded: 1440000000,
  percent: 100,
  active_file: null,
  error: null,
};

const mockNotDownloadedStatus: ModelStatusInfo = {
  repo: 'ggml-org/GLM-OCR-GGUF',
  revision: '65a42de',
  downloaded: false,
  model_path: null,
  mmproj_path: null,
  total_bytes: 1440000000,
  is_downloading: false,
  bytes_downloaded: 0,
  percent: 0,
  active_file: null,
  error: null,
};

const mockDownloadingStatus: ModelStatusInfo = {
  repo: 'ggml-org/GLM-OCR-GGUF',
  revision: '65a42de',
  downloaded: false,
  model_path: null,
  mmproj_path: null,
  total_bytes: 1440000000,
  is_downloading: true,
  bytes_downloaded: 720000000,
  percent: 50,
  active_file: 'glm-ocr-q8_0.gguf',
  error: null,
};

describe('Model Weights Management UI and Download Workflow', () => {
  const originalFetch = global.fetch;
  const originalEventSource = global.EventSource;

  beforeEach(() => {
    vi.restoreAllMocks();
    MockEventSource.instances = [];
    global.EventSource = MockEventSource as any;

    global.fetch = vi.fn().mockImplementation((url: string) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/model/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockNotDownloadedStatus,
        } as Response);
      }
      if (urlStr.includes('/api/server/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: 'offline',
            ownership: 'none',
            managed_by_web: false,
            message: 'Server offline',
            endpoint: 'http://127.0.0.1:8080',
            pid: null,
            recent_logs: [],
          }),
        } as Response);
      }
      if (urlStr.includes('/api/settings')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({}),
        } as Response);
      }
      if (urlStr.includes('/api/doctor')) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: async () => ({ report: null }),
        } as Response);
      }
      if (urlStr.includes('/api/documents')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => [],
        } as Response);
      }
      if (urlStr.includes('/health')) {
        return Promise.resolve({
          ok: false,
          status: 503,
          json: async () => ({ status: 'offline' }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      } as Response);
    });
  });

  afterEach(() => {
    global.fetch = originalFetch;
    global.EventSource = originalEventSource;
  });

  // Test 1: renders model status from GET /api/model/status and displays downloaded badge
  it('renders model status from GET /api/model/status and displays downloaded badge', async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/model/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockDownloadedStatus,
        } as Response);
      }
      if (urlStr.includes('/api/settings')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({}),
        } as Response);
      }
      if (urlStr.includes('/api/doctor')) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: async () => ({ report: null }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      } as Response);
    });

    render(<SettingsView />);

    // Wait for model status to load and verify downloaded badge
    const badge = await screen.findByText(/Downloaded \(Verified Local Weights\)/i);
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass('bg-[#15803D]/10');
    expect(badge).toHaveClass('text-[#14532D]');

    // Verify metadata
    expect(screen.getByText('GLM-OCR (Q8_0)')).toBeInTheDocument();
    expect(screen.getByText(/ggml-org\/GLM-OCR-GGUF/)).toBeInTheDocument();
    expect(screen.getByText(/65a42de/)).toBeInTheDocument();
    expect(screen.getByText('1.34 GB')).toBeInTheDocument();

    // Verify Re-download button text when already downloaded
    expect(screen.getByRole('button', { name: /Re-download Weights/i })).toBeInTheDocument();
    expect(screen.getByText('Model verified & ready for offline inference.')).toBeInTheDocument();
  });

  // Test 2: displays "Not Downloaded (Using -hf fallback)" when not downloaded
  it('displays "Not Downloaded (Using -hf fallback)" when not downloaded', async () => {
    render(<SettingsView modelStatus={mockNotDownloadedStatus} />);

    const badge = await screen.findByText(/Not Downloaded \(Using -hf fallback\)/i);
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass('bg-amber-500/10');
    expect(badge).toHaveClass('text-amber-700');

    // Verify "Download Pinned Model" action button
    expect(screen.getByRole('button', { name: 'Download Pinned Model' })).toBeInTheDocument();
  });

  // Test 3: clicking "Download Pinned Model" calls POST /api/model/download
  it('clicking "Download Pinned Model" calls POST /api/model/download', async () => {
    const user = userEvent.setup();
    let downloadCalled = false;

    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/model/download') && init?.method === 'POST') {
        downloadCalled = true;
        return Promise.resolve({
          ok: true,
          status: 202,
          json: async () => ({ started: true, message: 'Model download initiated' }),
        } as Response);
      }
      if (urlStr.includes('/api/model/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockNotDownloadedStatus,
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      } as Response);
    });

    render(<SettingsView modelStatus={mockNotDownloadedStatus} />);

    const downloadBtn = await screen.findByRole('button', { name: 'Download Pinned Model' });
    await user.click(downloadBtn);

    await waitFor(() => {
      expect(downloadCalled).toBe(true);
    });
  });

  // Test 4: renders progress bar and Cancel button when is_downloading is true
  it('renders progress bar and Cancel button when is_downloading is true', async () => {
    render(<SettingsView modelStatus={mockDownloadingStatus} />);

    // Verify progress text and active file
    expect(await screen.findByText('glm-ocr-q8_0.gguf')).toBeInTheDocument();
    expect(screen.getByText(/50%/)).toBeInTheDocument();

    // Verify Cancel button is present
    const cancelBtn = screen.getByRole('button', { name: 'Cancel Download' });
    expect(cancelBtn).toBeInTheDocument();

    // Verify progress bar style width is 50%
    const progressBar = document.querySelector('div[style*="width: 50%"]');
    expect(progressBar).toBeInTheDocument();

    // Verify "Download Pinned Model" button is NOT rendered while downloading
    expect(screen.queryByRole('button', { name: 'Download Pinned Model' })).not.toBeInTheDocument();
  });

  // Test 5: clicking "Cancel Download" calls POST /api/model/download/cancel
  it('clicking "Cancel Download" calls POST /api/model/download/cancel', async () => {
    const user = userEvent.setup();
    let cancelCalled = false;

    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/model/download/cancel') && init?.method === 'POST') {
        cancelCalled = true;
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ cancelled: true, message: 'Download cancellation requested' }),
        } as Response);
      }
      if (urlStr.includes('/api/model/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockDownloadingStatus,
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      } as Response);
    });

    render(<SettingsView modelStatus={mockDownloadingStatus} />);

    const cancelBtn = await screen.findByRole('button', { name: 'Cancel Download' });
    await user.click(cancelBtn);

    await waitFor(() => {
      expect(cancelCalled).toBe(true);
    });
  });


  // Test 6: App integration receives model_download_progress SSE event and updates SettingsView
  it('App integration: receives model_download_progress SSE event and updates SettingsView', async () => {
    const user = userEvent.setup();

    global.fetch = vi.fn().mockImplementation((url: string) => {
      const urlStr = String(url);
      if (urlStr === '/api/server/status') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: 'ready',
            ownership: 'managed',
            managed_by_web: true,
            message: 'Ready',
            endpoint: 'http://127.0.0.1:8080',
            pid: 1234,
            recent_logs: [],
          }),
        } as Response);
      }
      if (urlStr === '/api/documents') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => [],
        } as Response);
      }
      if (urlStr === '/api/model/status') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockNotDownloadedStatus,
        } as Response);
      }
      if (urlStr === '/health') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'ok' }),
        } as Response);
      }
      if (urlStr.includes('/api/doctor')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ checks: [] }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      } as Response);
    });

    render(<App />);

    // Navigate to Settings tab
    const settingsNavBtn = await screen.findByRole('button', { name: 'Settings' });
    await user.click(settingsNavBtn);

    // Initial state: Not Downloaded
    expect(await screen.findByText(/Not Downloaded \(Using -hf fallback\)/i)).toBeInTheDocument();

    // Broadcast SSE progress event
    const sseInstance = MockEventSource.instances[0];
    expect(sseInstance).toBeDefined();

    act(() => {
      sseInstance.emit('model_download_progress', {
        is_downloading: true,
        bytes_downloaded: 720000000,
        total_bytes: 1440000000,
        percent: 50,
        active_file: 'glm-ocr-q8_0.gguf',
        error: null,
      });
    });

    // Verify progress UI appears in SettingsView
    expect(await screen.findByText('Cancel Download')).toBeInTheDocument();
    expect(screen.getByText('glm-ocr-q8_0.gguf')).toBeInTheDocument();
    expect(screen.getByText(/50%/)).toBeInTheDocument();
  });

  // Test 7: clicking "Re-download Weights" prompts confirmation and aborts if dismissed
  it('clicking "Re-download Weights" prompts confirmation and aborts if dismissed', async () => {
    const user = userEvent.setup();
    let downloadCalled = false;
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);

    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/model/download') && init?.method === 'POST') {
        downloadCalled = true;
        return Promise.resolve({
          ok: true,
          status: 202,
          json: async () => ({ started: true }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => mockDownloadedStatus,
      } as Response);
    });

    render(<SettingsView modelStatus={mockDownloadedStatus} />);

    const redownloadBtn = await screen.findByRole('button', { name: 'Re-download Weights' });
    await user.click(redownloadBtn);

    expect(confirmSpy).toHaveBeenCalledWith(
      'Model weights are already verified and installed locally. Do you want to re-download the ~1.4 GB model from Hugging Face?'
    );
    expect(downloadCalled).toBe(false);
  });

  // Test 8: clicking "Re-download Weights" prompts confirmation and proceeds if confirmed
  it('clicking "Re-download Weights" prompts confirmation and proceeds if confirmed', async () => {
    const user = userEvent.setup();
    let downloadCalled = false;
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/model/download') && init?.method === 'POST') {
        downloadCalled = true;
        return Promise.resolve({
          ok: true,
          status: 202,
          json: async () => ({ started: true }),
        } as Response);
      }
      if (urlStr.includes('/api/model/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockDownloadedStatus,
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      } as Response);
    });

    render(<SettingsView modelStatus={mockDownloadedStatus} />);

    const redownloadBtn = await screen.findByRole('button', { name: 'Re-download Weights' });
    await user.click(redownloadBtn);

    expect(confirmSpy).toHaveBeenCalledWith(
      'Model weights are already verified and installed locally. Do you want to re-download the ~1.4 GB model from Hugging Face?'
    );
    await waitFor(() => {
      expect(downloadCalled).toBe(true);
    });
  });

  // Test 9: App integration: model download completion event updates status badge immediately to Downloaded without refresh
  it('App integration: model download completion event updates status badge immediately to Downloaded without refresh', async () => {
    const user = userEvent.setup();
    let currentStatus = mockNotDownloadedStatus;

    global.fetch = vi.fn().mockImplementation((url: string) => {
      const urlStr = String(url);
      if (urlStr === '/api/server/status') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: 'ready',
            ownership: 'managed',
            managed_by_web: true,
            message: 'Ready',
            endpoint: 'http://127.0.0.1:8080',
            pid: 1234,
            recent_logs: [],
          }),
        } as Response);
      }
      if (urlStr === '/api/documents') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => [],
        } as Response);
      }
      if (urlStr === '/api/model/status') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => currentStatus,
        } as Response);
      }
      if (urlStr === '/api/settings') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ dpi: 100 }),
        } as Response);
      }
      if (urlStr === '/health') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'ok' }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      } as Response);
    });

    render(<App />);

    const settingsNavBtn = await screen.findByRole('button', { name: 'Settings' });
    await user.click(settingsNavBtn);

    expect(await screen.findByText(/Not Downloaded \(Using -hf fallback\)/i)).toBeInTheDocument();

    const sseInstance = MockEventSource.instances[0];
    expect(sseInstance).toBeDefined();

    currentStatus = mockDownloadedStatus;
    act(() => {
      sseInstance.emit('model_download_progress', {
        status: 'completed',
        is_downloading: false,
        bytes_downloaded: 1440000000,
        total_bytes: 1440000000,
        percent: 100,
        downloaded: true,
        active_file: null,
        error: null,
      });
    });

    expect(await screen.findByText(/Downloaded \(Verified Local Weights\)/i)).toBeInTheDocument();
  });
});
