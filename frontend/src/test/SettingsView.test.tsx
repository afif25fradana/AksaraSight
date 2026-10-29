import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, within, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SettingsView } from '../components/SettingsView';
import { BackendSettings } from '../types';

const mockDefaultSettings: BackendSettings = {
  backend: 'llama-cpp',
  local_endpoint: 'http://127.0.0.1:8080/v1',
  runtime_mode: 'managed',
  managed_backend_override: 'cuda',
  dpi: 100,
  max_image_dimension: 2048,
  max_tokens: 4096,
  timeout: 60,
  max_retries: 2,
  auto_start_server: false,
  model_repo: 'ggml-org/GLM-OCR-GGUF',
  allow_remote: false,
  llama_server_path: null,
};

const mockRuntimeStatus = {
  installed: false,
  is_downloading: false,
  active_tag: 'b11361',
  recommended_backend: 'cpu',
};

describe('SettingsView backend integration and security', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('renders mutable backend radios, runtime mode pills, and allows custom binary selection via browse dialog', async () => {
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/settings') && (!init || !init.method || init.method === 'GET')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockDefaultSettings,
        } as Response);
      }
      if (urlStr.includes('/api/runtime/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockRuntimeStatus,
        } as Response);
      }
      if (urlStr.includes('/api/doctor') && (!init || !init.method || init.method === 'GET')) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: async () => ({ report: null }),
        } as Response);
      }
      if (urlStr.includes('/api/dialog/file') && init?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ path: 'C:\\tools\\llama-server.exe' }),
        } as Response);
      }
      return Promise.reject(new Error(`Unhandled fetch: ${urlStr}`));
    });

    render(<SettingsView />);

    // Wait for backend settings to load
    expect(await screen.findByText('llama-cpp')).toBeInTheDocument();

    // Verify Read-Only badges are completely removed
    expect(screen.queryByText('Read-Only')).not.toBeInTheDocument();

    // Verify backend radios are rendered and selectable
    const llamaRadio = screen.getByRole('radio', { name: /llama-cpp/i });
    const ollamaRadio = screen.getByRole('radio', { name: /ollama/i });
    expect(llamaRadio).toBeChecked();
    expect(ollamaRadio).not.toBeChecked();

    await userEvent.click(ollamaRadio);
    expect(ollamaRadio).toBeChecked();

    // Verify runtime mode segmented buttons
    const managedBtn = screen.getByRole('button', { name: 'Managed Local Runtime' });
    const customBtn = screen.getByRole('button', { name: 'Custom Executable Path' });
    expect(managedBtn).toBeInTheDocument();
    expect(customBtn).toBeInTheDocument();

    // Switch to Custom Executable Path
    await userEvent.click(customBtn);

    // Custom path input and Browse button should now appear
    const customPathInput = screen.getByLabelText(/Custom llama-server Executable Path/i);
    expect(customPathInput).toBeInTheDocument();

    const browseBtn = screen.getByRole('button', { name: /Browse\.\.\./i });
    expect(browseBtn).toBeInTheDocument();

    // Click Browse...
    await userEvent.click(browseBtn);
    await waitFor(() => {
      expect(customPathInput).toHaveValue('C:\\tools\\llama-server.exe');
    });
    expect(screen.getByText('Custom llama-server binary configured')).toBeInTheDocument();
  });

  it('renders Advanced tab with editable endpoint, model repo, and remote security confirmation modal', async () => {
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/settings') && (!init || !init.method || init.method === 'GET')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockDefaultSettings,
        } as Response);
      }
      if (urlStr.includes('/api/runtime/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockRuntimeStatus,
        } as Response);
      }
      if (urlStr.includes('/api/doctor') && (!init || !init.method || init.method === 'GET')) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: async () => ({ report: null }),
        } as Response);
      }
      return Promise.reject(new Error(`Unhandled fetch: ${urlStr}`));
    });

    render(<SettingsView />);
    await screen.findByText('llama-cpp');

    // Switch to Advanced & Network tab
    const advancedTab = screen.getByRole('tab', { name: /Advanced/i });
    await userEvent.click(advancedTab);

    // Verify endpoint input is editable
    const endpointInput = screen.getByLabelText(/Local Engine HTTP Endpoint URL/i);
    expect(endpointInput).toHaveValue('http://127.0.0.1:8080/v1');
    await userEvent.clear(endpointInput);
    await userEvent.type(endpointInput, 'http://127.0.0.1:9090/v1');
    expect(endpointInput).toHaveValue('http://127.0.0.1:9090/v1');

    // Verify model_repo input is editable
    const modelRepoInput = screen.getByLabelText(/Hugging Face Model Repository/i);
    expect(modelRepoInput).toHaveValue('ggml-org/GLM-OCR-GGUF');
    await userEvent.clear(modelRepoInput);
    await userEvent.type(modelRepoInput, 'custom-org/model-gguf');
    expect(modelRepoInput).toHaveValue('custom-org/model-gguf');

    // Verify remote endpoint toggle opens security modal
    const remoteSwitch = screen.getByRole('switch', { name: /Allow Non-Loopback \(Remote\) Endpoints/i });
    expect(remoteSwitch).toHaveAttribute('aria-checked', 'false');

    // Click toggle to turn remote ON -> should open Security Confirmation Modal
    await userEvent.click(remoteSwitch);

    const modal = screen.getByRole('alertdialog');
    expect(modal).toBeInTheDocument();
    expect(screen.getByText('Security Notice: Remote Endpoint')).toBeInTheDocument();
    expect(screen.getByText('Violates 100% Local Guarantee')).toBeInTheDocument();

    // Cancel modal first
    const cancelModalBtn = within(modal).getByRole('button', { name: 'Cancel' });
    await userEvent.click(cancelModalBtn);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(remoteSwitch).toHaveAttribute('aria-checked', 'false');

    // Click toggle again and confirm
    await userEvent.click(remoteSwitch);
    const modalAfter = screen.getByRole('alertdialog');
    const confirmBtn = within(modalAfter).getByRole('button', { name: 'I understand, enable remote' });
    await userEvent.click(confirmBtn);

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(remoteSwitch).toHaveAttribute('aria-checked', 'true');

    // Clicking switch again disables remote directly without modal
    await userEvent.click(remoteSwitch);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(remoteSwitch).toHaveAttribute('aria-checked', 'false');
  });

  it('modifying multiple mutable settings and saving triggers PATCH /api/settings with all modified mutable fields', async () => {
    let patchBody: any = null;

    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/settings')) {
        if (init?.method === 'PATCH') {
          patchBody = JSON.parse(String(init.body));
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              updated: true,
              settings: { ...mockDefaultSettings, ...patchBody },
            }),
          } as Response);
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockDefaultSettings,
        } as Response);
      }
      if (urlStr.includes('/api/runtime/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockRuntimeStatus,
        } as Response);
      }
      if (urlStr.includes('/api/doctor')) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: async () => ({ report: null }),
        } as Response);
      }
      return Promise.reject(new Error(`Unhandled fetch: ${urlStr}`));
    });

    render(<SettingsView />);
    await screen.findByText('llama-cpp');

    // 1. In Engine tab: change backend to 'vllm'
    const vllmRadio = screen.getByRole('radio', { name: /vllm/i });
    await userEvent.click(vllmRadio);

    // 2. In Processing & Quality tab: change DPI to 150
    const processingTab = screen.getByRole('tab', { name: /Processing/i });
    await userEvent.click(processingTab);
    const dpi150Btn = screen.getByRole('button', { name: '150 DPI' });
    await userEvent.click(dpi150Btn);

    // 3. In Advanced & Network tab: change local_endpoint and enable remote
    const advancedTab = screen.getByRole('tab', { name: /Advanced/i });
    await userEvent.click(advancedTab);
    const endpointInput = screen.getByLabelText(/Local Engine HTTP Endpoint URL/i);
    await userEvent.clear(endpointInput);
    await userEvent.type(endpointInput, 'http://192.168.1.100:8000/v1');

    const remoteSwitch = screen.getByRole('switch', { name: /Allow Non-Loopback \(Remote\) Endpoints/i });
    await userEvent.click(remoteSwitch);
    const confirmBtn = screen.getByRole('button', { name: 'I understand, enable remote' });
    await userEvent.click(confirmBtn);

    // Click Save Settings button
    const saveButton = screen.getByRole('button', { name: /Save Settings/i });
    expect(saveButton).not.toBeDisabled();
    await userEvent.click(saveButton);

    // Verify PATCH was called
    await waitFor(() => {
      expect(patchBody).not.toBeNull();
    });

    expect(patchBody).toEqual({
      backend: 'vllm',
      dpi: 150,
      local_endpoint: 'http://192.168.1.100:8000/v1',
      allow_remote: true,
    });

    // Verify success banner appears
    expect(await screen.findByText('Settings saved successfully')).toBeInTheDocument();
  });

  it('clicking "Run Doctor" triggers POST /api/doctor and renders actual returned check items', async () => {
    const mockDoctorResponse = {
      status: 'HEALTHY',
      exit_code: 0,
      total_checks: 2,
      failed_checks: 0,
      checks: [
        {
          category: 'Configuration',
          title: 'Configuration Valid',
          status: 'PASS',
          details: 'Backend parameters and local loopback endpoint verified',
          remediation: null,
        },
        {
          category: 'Hardware',
          title: 'Hardware Detection Probe',
          status: 'PASS',
          details: 'NVIDIA RTX 4090 GPU detected with CUDA support',
          remediation: null,
        },
      ],
      text: 'Diagnostic passed',
    };

    let postDoctorCalled = false;

    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/settings')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockDefaultSettings,
        } as Response);
      }
      if (urlStr.includes('/api/runtime/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockRuntimeStatus,
        } as Response);
      }
      if (urlStr.includes('/api/doctor')) {
        if (init?.method === 'POST') {
          postDoctorCalled = true;
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => mockDoctorResponse,
          } as Response);
        }
        return Promise.resolve({
          ok: false,
          status: 404,
          json: async () => ({ report: null }),
        } as Response);
      }
      return Promise.reject(new Error(`Unhandled fetch: ${urlStr}`));
    });

    render(<SettingsView />);
    await screen.findByText('llama-cpp');

    // Click Run Doctor button
    const runDoctorBtn = screen.getByRole('button', { name: /Run Doctor/i });
    await userEvent.click(runDoctorBtn);

    expect(postDoctorCalled).toBe(true);

    // Verify check items are rendered
    expect(await screen.findByText('Hardware Detection Probe')).toBeInTheDocument();
    expect(screen.getAllByText('NVIDIA RTX 4090 GPU detected with CUDA support').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Configuration Valid')).toBeInTheDocument();
  });

  it('handles PATCH /api/settings error by showing error message', async () => {
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/settings')) {
        if (init?.method === 'PATCH') {
          return Promise.resolve({
            ok: false,
            status: 400,
            json: async () => ({
              detail: "Invalid value for setting 'dpi'.",
            }),
          } as Response);
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockDefaultSettings,
        } as Response);
      }
      if (urlStr.includes('/api/runtime/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockRuntimeStatus,
        } as Response);
      }
      if (urlStr.includes('/api/doctor')) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: async () => ({ report: null }),
        } as Response);
      }
      return Promise.reject(new Error(`Unhandled fetch: ${urlStr}`));
    });

    render(<SettingsView />);
    await screen.findByText('llama-cpp');

    // Switch to Processing & Quality tab
    const processingTab = screen.getByRole('tab', { name: /Processing/i });
    await userEvent.click(processingTab);

    // Change DPI to 200
    const dpi200Btn = screen.getByRole('button', { name: '200 DPI' });
    await userEvent.click(dpi200Btn);

    // Click Save Settings
    const saveButton = screen.getByRole('button', { name: /Save Settings/i });
    await userEvent.click(saveButton);

    // Verify inline error banner appears with returned error detail
    const alertBanner = await screen.findByRole('alert');
    expect(alertBanner).toBeInTheDocument();
    expect(alertBanner).toHaveTextContent("Invalid value for setting 'dpi'.");
  });

  it('renders auto_start_server switch with updated Web UI copy', async () => {
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/settings') && (!init || !init.method || init.method === 'GET')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockDefaultSettings,
        } as Response);
      }
      if (urlStr.includes('/api/runtime/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockRuntimeStatus,
        } as Response);
      }
      if (urlStr.includes('/api/doctor') && (!init || !init.method || init.method === 'GET')) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: async () => ({ report: null }),
        } as Response);
      }
      return Promise.reject(new Error(`Unhandled fetch: ${urlStr}`));
    });

    render(<SettingsView />);
    expect(await screen.findByText('Start engine automatically with Web UI')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Start engine automatically with Web UI' })).toBeInTheDocument();
    expect(screen.queryByText(/with GUI/i)).not.toBeInTheDocument();
  });

  it('displays multi-part download progress indicator when runtime download is in progress', async () => {
    const downloadingStatus = {
      installed: false,
      is_downloading: true,
      tag: 'b11361',
      backend: 'cuda',
      executable_path: null,
      expected_path: 'C:\\runtimes\\llama-server.exe',
      message: 'Downloading cudart-llama-bin-win-cuda-12.4-x64.zip...',
      bytes_downloaded: 10485760,
      total_bytes: 20971520,
      percent: 50.0,
      part: 1,
      total_parts: 2,
      error: null,
    };

    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/settings') && (!init || !init.method || init.method === 'GET')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockDefaultSettings,
        } as Response);
      }
      if (urlStr.includes('/api/runtime/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => downloadingStatus,
        } as Response);
      }
      if (urlStr.includes('/api/doctor')) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: async () => ({ report: null }),
        } as Response);
      }
      return Promise.reject(new Error(`Unhandled fetch: ${urlStr}`));
    });

    render(<SettingsView />);
    expect(await screen.findByText('Downloading cudart-llama-bin-win-cuda-12.4-x64.zip...')).toBeInTheDocument();
    expect(screen.getByText('Part 1 of 2')).toBeInTheDocument();
  });

  it('triggers POST /api/runtime/download when Download Runtime is clicked and updates on SSE progress', async () => {
    let runtimeStatus = {
      installed: false,
      is_downloading: false,
      active_tag: 'b11361',
      recommended_backend: 'cuda',
      executable_path: null,
      expected_path: 'C:\\runtimes\\llama-server.exe',
      message: '',
      bytes_downloaded: 0,
      total_bytes: 0,
      percent: 0,
      error: null,
    };

    let downloadPostCalled = false;
    const eventListeners: Record<string, ((e: MessageEvent) => void)[]> = {};

    const mockEventSource = {
      addEventListener: vi.fn((event: string, cb: (e: MessageEvent) => void) => {
        if (!eventListeners[event]) eventListeners[event] = [];
        eventListeners[event].push(cb);
      }),
      removeEventListener: vi.fn(),
      close: vi.fn(),
    };
    (window as any).__eventSource = mockEventSource;

    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/settings')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockDefaultSettings,
        } as Response);
      }
      if (urlStr.includes('/api/runtime/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => runtimeStatus,
        } as Response);
      }
      if (urlStr.includes('/api/runtime/download') && init?.method === 'POST') {
        downloadPostCalled = true;
        runtimeStatus = { ...runtimeStatus, is_downloading: true };
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'started' }),
        } as Response);
      }
      if (urlStr.includes('/api/doctor')) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: async () => ({ report: null }),
        } as Response);
      }
      return Promise.reject(new Error(`Unhandled fetch: ${urlStr}`));
    });

    render(<SettingsView />);

    // Wait for Download Runtime button to appear
    const downloadBtn = await screen.findByRole('button', { name: /download runtime/i });
    expect(downloadBtn).toBeInTheDocument();

    await userEvent.click(downloadBtn);
    expect(downloadPostCalled).toBe(true);

    // Simulate runtime_download_progress SSE event
    const sseHandler = eventListeners['runtime_download_progress']?.[0];
    expect(sseHandler).toBeDefined();

    if (sseHandler) {
      act(() => {
        sseHandler({
          data: JSON.stringify({
            is_downloading: true,
            bytes_downloaded: 5242880,
            total_bytes: 10485760,
            percent: 50.0,
            message: 'Extracting runtime archive...',
          }),
        } as MessageEvent);
      });
    }

    expect(await screen.findByText('Extracting runtime archive...')).toBeInTheDocument();
    delete (window as any).__eventSource;
  });
});
