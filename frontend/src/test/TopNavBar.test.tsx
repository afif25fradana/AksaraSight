import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TopNavBar } from '../components/workspace/TopNavBar';
import { ServerStatusInfo, VramTelemetry } from '../types';
import { INITIAL_SETTINGS } from '../data/mockDocuments';

describe('TopNavBar Component and VRAM Telemetry Badge', () => {
  const defaultStatus: ServerStatusInfo = {
    status: 'ready',
    ownership: 'managed',
    managed_by_web: true,
    message: 'Server ready',
    endpoint: 'http://127.0.0.1:8080/v1',
    pid: 1234,
    recent_logs: [],
  };

  const defaultProps = {
    currentTab: 'workspace' as const,
    onSelectTab: vi.fn(),
    engineSettings: INITIAL_SETTINGS,
    onToggleServer: vi.fn(),
    onOpenServerLogs: vi.fn(),
    onOpenOutputFolder: vi.fn(),
    theme: 'light' as const,
    onToggleTheme: vi.fn(),
    serverStatus: defaultStatus,
    isExtracting: false,
    isTransitioning: false,
  };

  it('renders live total and used MB telemetry badge when VRAM is available', () => {
    const liveVram: VramTelemetry = {
      available: true,
      total_mb: 8192,
      used_mb: 2048,
      device_name: 'NVIDIA GeForce RTX 4070',
      usage_percent: 25,
    };

    render(<TopNavBar {...defaultProps} vram={liveVram} />);

    const vramGauge = screen.getByLabelText('VRAM Telemetry Gauge');
    expect(vramGauge).toBeInTheDocument();
    expect(vramGauge).toHaveAttribute(
      'title',
      'GPU: NVIDIA GeForce RTX 4070 | VRAM: 2048MB / 8192MB'
    );
    expect(screen.getByText('2.0 / 8.0 GB')).toBeInTheDocument();
  });

  it('renders fallback disabled badge when VRAM telemetry is unavailable (available: false)', () => {
    const unavailableVram: VramTelemetry = {
      available: false,
      error: 'CUDA runtime not detected on host system',
    };

    render(<TopNavBar {...defaultProps} vram={unavailableVram} />);

    const fallbackBadge = screen.getByLabelText('VRAM Telemetry Unavailable');
    expect(fallbackBadge).toBeInTheDocument();
    expect(fallbackBadge).toHaveTextContent('VRAM N/A');
    expect(fallbackBadge).toHaveAttribute('title', 'CUDA runtime not detected on host system');
  });

  it('renders PaddleOCR-VL model indicator text when engine is ready', () => {
    render(<TopNavBar {...defaultProps} vram={null} />);

    expect(screen.getByText(/PaddleOCR-VL/i)).toBeInTheDocument();
  });
});
