import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';
import { TopNavBar } from '../components/TopNavBar';
import { ServerLogsModal } from '../components/ServerLogsModal';
import { EngineSettings, ServerStatusInfo } from '../types';

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

const mockDefaultSettings: EngineSettings = {
  status: 'offline',
  backend: 'llama-cpp',
  local_endpoint: 'http://127.0.0.1:8080/v1',
  dpi: 100,
  max_image_dimension: 2048,
  max_tokens: 4096,
  timeout: 60,
  max_retries: 2,
  auto_start_server: false,
  model_repo: 'ggml-org/GLM-OCR-GGUF',
};

describe('ServerControls and Live Log Viewer State Machine', () => {
  const originalFetch = global.fetch;
  const originalEventSource = global.EventSource;

  beforeEach(() => {
    vi.restoreAllMocks();
    MockEventSource.instances = [];
    global.EventSource = MockEventSource as any;
  });

  afterEach(() => {
    global.fetch = originalFetch;
    global.EventSource = originalEventSource;
  });

  // Test 1: Start Server calls POST /api/server/start when server is offline
  it('calls POST /api/server/start when Start Server button is clicked in offline state', async () => {
    const user = userEvent.setup();

    const offlineStatus: ServerStatusInfo = {
      status: 'offline',
      ownership: 'none',
      managed_by_web: false,
      message: 'Server is offline',
      endpoint: 'http://127.0.0.1:8080',
      pid: null,
      recent_logs: [],
    };

    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr === '/api/server/status' && (!init || !init.method || init.method === 'GET')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => offlineStatus,
        } as Response);
      }
      if (urlStr === '/api/documents') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => [],
        } as Response);
      }
      if (urlStr === '/health') {
        return Promise.resolve({
          ok: false,
          status: 503,
          json: async () => ({ status: 'error' }),
        } as Response);
      }
      if (urlStr === '/api/server/start' && init?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ started: true, status: 'ready', ownership: 'managed', message: 'Server started' }),
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

    // Wait for Start Server button to appear
    const startButton = await screen.findByRole('button', { name: 'Start Server' });
    expect(startButton).toBeInTheDocument();
    expect(startButton).not.toBeDisabled();

    await user.click(startButton);

    await waitFor(() => {
      const startCalls = fetchMock.mock.calls.filter(
        ([url, init]) => String(url) === '/api/server/start' && init?.method === 'POST'
      );
      expect(startCalls).toHaveLength(1);
    });
  });

  // Test 2: Stop Server calls POST /api/server/stop when server is managed and ready
  it('calls POST /api/server/stop when Stop Server button is clicked in managed ready state', async () => {
    const user = userEvent.setup();

    const readyStatus: ServerStatusInfo = {
      status: 'ready',
      ownership: 'managed',
      managed_by_web: true,
      message: 'Server is ready',
      endpoint: 'http://127.0.0.1:8080',
      pid: 2468,
      recent_logs: [],
    };

    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr === '/api/server/status' && (!init || !init.method || init.method === 'GET')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => readyStatus,
        } as Response);
      }
      if (urlStr === '/api/documents') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => [],
        } as Response);
      }
      if (urlStr === '/health') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'ok' }),
        } as Response);
      }
      if (urlStr === '/api/server/stop' && init?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ stopped: true, status: 'offline', ownership: 'none', message: 'Server stopped' }),
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

    // Wait for Local Engine Ready indicator and PID badge
    expect(await screen.findByText('Local Engine Ready')).toBeInTheDocument();
    expect(screen.getByText('PID 2468')).toBeInTheDocument();

    const stopButton = await screen.findByRole('button', { name: 'Stop Server' });
    expect(stopButton).toBeInTheDocument();
    expect(stopButton).not.toBeDisabled();

    await user.click(stopButton);

    await waitFor(() => {
      const stopCalls = fetchMock.mock.calls.filter(
        ([url, init]) => String(url) === '/api/server/stop' && init?.method === 'POST'
      );
      expect(stopCalls).toHaveLength(1);
    });
  });

  // Test 3: Stop Server is disabled with appropriate title when server is external (ownership: 'external')
  it('disables Stop Server button with external ownership tooltip when server is external', () => {
    const onToggleServer = vi.fn();
    const externalStatus: ServerStatusInfo = {
      status: 'ready',
      ownership: 'external',
      managed_by_web: false,
      message: 'Running externally',
      endpoint: 'http://127.0.0.1:8080',
      pid: 9999,
      recent_logs: [],
    };

    render(
      <TopNavBar
        currentTab="workspace"
        onSelectTab={vi.fn()}
        engineSettings={mockDefaultSettings}
        onToggleServer={onToggleServer}
        onOpenServerLogs={vi.fn()}
        onOpenOutputFolder={vi.fn()}
        theme="light"
        onToggleTheme={vi.fn()}
        serverStatus={externalStatus}
        isExtracting={false}
      />
    );

    const stopButton = screen.getByRole('button', {
      name: 'Stop Server (Disabled - External Server)',
    });
    expect(stopButton).toBeInTheDocument();
    expect(stopButton).toBeDisabled();
    expect(stopButton).toHaveAttribute('title', 'Server managed externally (PID 9999)');
  });

  // Test 4: Stop Server is disabled when extraction is in progress (isExtracting: true)
  it('disables Stop Server button with extraction in progress tooltip when isExtracting is true', () => {
    const onToggleServer = vi.fn();
    const managedReadyStatus: ServerStatusInfo = {
      status: 'ready',
      ownership: 'managed',
      managed_by_web: true,
      message: 'Running managed',
      endpoint: 'http://127.0.0.1:8080',
      pid: 1234,
      recent_logs: [],
    };

    render(
      <TopNavBar
        currentTab="workspace"
        onSelectTab={vi.fn()}
        engineSettings={mockDefaultSettings}
        onToggleServer={onToggleServer}
        onOpenServerLogs={vi.fn()}
        onOpenOutputFolder={vi.fn()}
        theme="light"
        onToggleTheme={vi.fn()}
        serverStatus={managedReadyStatus}
        isExtracting={true}
      />
    );

    const stopButton = screen.getByRole('button', {
      name: 'Stop Server (Disabled - Extraction in progress)',
    });
    expect(stopButton).toBeInTheDocument();
    expect(stopButton).toBeDisabled();
    expect(stopButton).toHaveAttribute('title', 'Extraction in progress');
  });

  // Test 5: ServerLogsModal opens EventSource('/api/server/logs/stream'), displays incoming lines, and calls eventSource.close() on unmount/close
  it('opens EventSource stream, renders incoming log lines, and calls close() on unmount', async () => {
    const onClose = vi.fn();
    const readyStatus: ServerStatusInfo = {
      status: 'ready',
      ownership: 'managed',
      managed_by_web: true,
      message: 'Ready',
      endpoint: 'http://127.0.0.1:8080',
      pid: 14288,
      recent_logs: [],
    };

    const { unmount } = render(
      <ServerLogsModal
        isOpen={true}
        onClose={onClose}
        serverStatus={readyStatus}
      />
    );

    // Verify EventSource connected to /api/server/logs/stream
    const logStreams = MockEventSource.instances.filter(
      (es) => es.url === '/api/server/logs/stream'
    );
    expect(logStreams).toHaveLength(1);
    const es = logStreams[0];

    // Emit real log events
    act(() => {
      es.emit('log', { line: '[2026-10-13 03:00:00] [INFO] [ServerManager] Starting engine runtime...' });
      es.emit('log', { line: '[2026-10-13 03:00:02] [HEALTH] [ServerManager] Health check OK :8080' });
    });

    // Verify log lines are rendered
    expect(await screen.findByText(/Starting engine runtime/)).toBeInTheDocument();
    expect(screen.getByText(/Health check OK :8080/)).toBeInTheDocument();

    // Verify footer text format
    expect(
      screen.getByText(/Showing 2 of 2 entries · In-memory log buffer \(bounded\) · No OCR text recorded/)
    ).toBeInTheDocument();

    // Unmount modal and verify es.close() is called
    unmount();
    expect(es.close).toHaveBeenCalledTimes(1);
  });
});
