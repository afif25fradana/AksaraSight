import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { BottomStatusBar } from '../components/workspace/BottomStatusBar';
import { ServerStatusInfo, VramTelemetry } from '../types';

describe('BottomStatusBar Component', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('renders Engine Ready status with PID and model indicator', async () => {
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: async () => ({ available: false }),
      } as Response)
    );

    const readyStatus: ServerStatusInfo = {
      status: 'ready',
      ownership: 'managed',
      managed_by_web: true,
      message: 'Engine running',
      endpoint: 'http://127.0.0.1:8080',
      pid: 4321,
      recent_logs: [],
    };

    await act(async () => {
      render(<BottomStatusBar serverStatus={readyStatus} />);
    });

    expect(screen.getByText('Engine Ready')).toBeInTheDocument();
    expect(screen.getByText('PID 4321')).toBeInTheDocument();
    expect(screen.getByText(/PaddleOCR-VL/)).toBeInTheDocument();
  });

  it('renders Starting Engine status with ping animation', async () => {
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: async () => ({ available: false }),
      } as Response)
    );

    const startingStatus: ServerStatusInfo = {
      status: 'starting',
      ownership: 'managed',
      managed_by_web: true,
      message: 'Starting runtime',
      endpoint: 'http://127.0.0.1:8080',
      pid: 5678,
      recent_logs: [],
    };

    await act(async () => {
      render(<BottomStatusBar serverStatus={startingStatus} />);
    });

    expect(screen.getByText('Starting Engine...')).toBeInTheDocument();
    expect(screen.getByText('PID 5678')).toBeInTheDocument();
  });

  it('renders Engine Offline status when status is offline or null', async () => {
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: async () => ({ available: false }),
      } as Response)
    );

    await act(async () => {
      render(<BottomStatusBar serverStatus={null} />);
    });

    expect(screen.getByText('Engine Offline')).toBeInTheDocument();
  });

  it('renders NVML VRAM telemetry gauge when GPU telemetry is available', async () => {
    const mockVram: VramTelemetry = {
      available: true,
      total_mb: 8192,
      used_mb: 2048,
      device_name: 'NVIDIA GeForce RTX 4070',
      usage_percent: 25,
    };

    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/hardware/vram')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockVram,
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({}),
      } as Response);
    });

    await act(async () => {
      render(<BottomStatusBar serverStatus={null} />);
    });

    const gauge = await screen.findByLabelText('VRAM Telemetry Gauge');
    expect(gauge).toBeInTheDocument();
    expect(screen.getByText('NVIDIA GeForce RTX 4070')).toBeInTheDocument();
    expect(screen.getByText('2048 / 8192 MB')).toBeInTheDocument();
    expect(screen.getByText('25%')).toBeInTheDocument();
  });

  it('renders fallback badge when VRAM telemetry is unavailable (CPU mode)', async () => {
    const mockUnavailable: VramTelemetry = {
      available: false,
      error: 'VRAM telemetry unavailable (CPU inference)',
    };

    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes('/api/hardware/vram')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockUnavailable,
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({}),
      } as Response);
    });

    await act(async () => {
      render(<BottomStatusBar serverStatus={null} />);
    });

    const unavailableBadge = await screen.findByLabelText('VRAM Telemetry Unavailable');
    expect(unavailableBadge).toBeInTheDocument();
    expect(screen.getByText('VRAM N/A (CPU)')).toBeInTheDocument();
  });

  it('renders implicit contentinfo landmark without redundant role and excludes duplicate Server Logs button', async () => {
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: async () => ({ available: false }),
      } as Response)
    );

    await act(async () => {
      render(<BottomStatusBar serverStatus={null} />);
    });

    const footer = screen.getByRole('contentinfo');
    expect(footer).toBeInTheDocument();
    expect(footer.tagName.toLowerCase()).toBe('footer');
    expect(footer.getAttribute('role')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Server Logs' })).not.toBeInTheDocument();
  });
});
