import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
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

describe('SettingsView backend integration and security', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('renders settings from GET /api/settings and displays immutable fields as read-only', async () => {
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/settings') && (!init || !init.method || init.method === 'GET')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => mockDefaultSettings,
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

    // Wait for backend settings to load
    expect(await screen.findByText('llama-cpp')).toBeInTheDocument();

    // Verify immutable fields are displayed with read-only badges
    const readOnlyBadges = screen.getAllByText('Read-Only');
    expect(readOnlyBadges.length).toBeGreaterThanOrEqual(2);

    // Verify backend is rendered as text and NOT as an editable input or radio button
    expect(screen.queryByRole('radio', { name: /llama-cpp/i })).not.toBeInTheDocument();

    // Verify runtime mode is rendered read-only
    expect(screen.getByText('managed')).toBeInTheDocument();

    // Switch to Advanced & Network tab to check endpoint and model_repo immutability
    const advancedTab = screen.getByRole('tab', { name: /Advanced/i });
    await userEvent.click(advancedTab);

    expect(screen.getByText('http://127.0.0.1:8080/v1')).toBeInTheDocument();
    expect(screen.getByText('ggml-org/GLM-OCR-GGUF')).toBeInTheDocument();
    expect(screen.getByText('100% Local-Only Invariant')).toBeInTheDocument();
  });

  it('modifying a mutable setting and saving triggers PATCH /api/settings with ONLY changed mutable fields', async () => {
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

    // Change DPI by clicking 150 DPI button
    const dpi150Btn = screen.getByRole('button', { name: '150 DPI' });
    await userEvent.click(dpi150Btn);

    // Click Save Settings button
    const saveButton = screen.getByRole('button', { name: /Save Settings/i });
    expect(saveButton).not.toBeDisabled();
    await userEvent.click(saveButton);

    // Verify PATCH was called
    await waitFor(() => {
      expect(patchBody).not.toBeNull();
    });

    // Ensure only the mutable dpi field was sent, and NO immutable fields
    expect(patchBody).toEqual({ dpi: 150 });
    expect(patchBody.backend).toBeUndefined();
    expect(patchBody.runtime_mode).toBeUndefined();
    expect(patchBody.local_endpoint).toBeUndefined();

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
});
