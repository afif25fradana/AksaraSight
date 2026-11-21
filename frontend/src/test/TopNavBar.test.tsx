import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TopNavBar } from '../components/workspace/TopNavBar';
import { ServerStatusInfo } from '../types';

describe('TopNavBar Component with Pruned Props', () => {
  const readyStatus: ServerStatusInfo = {
    status: 'ready',
    ownership: 'managed',
    managed_by_web: true,
    message: 'Server ready',
    endpoint: 'http://127.0.0.1:8080/v1',
    pid: 1234,
    recent_logs: [],
  };

  const offlineStatus: ServerStatusInfo = {
    status: 'offline',
    ownership: 'none',
    managed_by_web: false,
    message: 'Server offline',
    endpoint: 'http://127.0.0.1:8080/v1',
    pid: null,
    recent_logs: [],
  };

  it('renders brand title and subtitle', () => {
    render(
      <TopNavBar
        onToggleServer={vi.fn()}
        onOpenOutputFolder={vi.fn()}
        serverStatus={offlineStatus}
        isExtracting={false}
      />
    );

    expect(screen.getByRole('heading', { level: 1, name: 'AksaraSight' })).toBeInTheDocument();
    expect(screen.getByText('Local Archival & Document OCR')).toBeInTheDocument();
  });

  it('renders Start Engine button when offline and handles click', async () => {
    const user = userEvent.setup();
    const handleToggle = vi.fn();

    render(
      <TopNavBar
        onToggleServer={handleToggle}
        onOpenOutputFolder={vi.fn()}
        serverStatus={offlineStatus}
        isExtracting={false}
        isTransitioning={false}
      />
    );

    const startBtn = screen.getByRole('button', { name: 'Start Engine' });
    expect(startBtn).toBeInTheDocument();
    expect(startBtn).not.toBeDisabled();

    await user.click(startBtn);
    expect(handleToggle).toHaveBeenCalledTimes(1);
  });

  it('renders Stop Engine button when ready and handles click', async () => {
    const user = userEvent.setup();
    const handleToggle = vi.fn();

    render(
      <TopNavBar
        onToggleServer={handleToggle}
        onOpenOutputFolder={vi.fn()}
        serverStatus={readyStatus}
        isExtracting={false}
        isTransitioning={false}
      />
    );

    const stopBtn = screen.getByRole('button', { name: 'Stop Engine' });
    expect(stopBtn).toBeInTheDocument();
    expect(stopBtn).not.toBeDisabled();

    await user.click(stopBtn);
    expect(handleToggle).toHaveBeenCalledTimes(1);
  });

  it('disables Stop Engine when server ownership is external', () => {
    const externalStatus: ServerStatusInfo = {
      ...readyStatus,
      ownership: 'external',
      pid: 9999,
    };

    render(
      <TopNavBar
        onToggleServer={vi.fn()}
        onOpenOutputFolder={vi.fn()}
        serverStatus={externalStatus}
        isExtracting={false}
      />
    );

    const stopBtn = screen.getByRole('button', {
      name: 'Stop Engine (Disabled - External Server)',
    });
    expect(stopBtn).toBeInTheDocument();
    expect(stopBtn).toBeDisabled();
  });

  it('disables Stop Engine when extraction is in progress', () => {
    render(
      <TopNavBar
        onToggleServer={vi.fn()}
        onOpenOutputFolder={vi.fn()}
        serverStatus={readyStatus}
        isExtracting={true}
      />
    );

    const stopBtn = screen.getByRole('button', {
      name: 'Stop Engine (Disabled - Extraction in progress)',
    });
    expect(stopBtn).toBeInTheDocument();
    expect(stopBtn).toBeDisabled();
  });

  it('shows transitioning state when starting or stopping', () => {
    const { rerender } = render(
      <TopNavBar
        onToggleServer={vi.fn()}
        onOpenOutputFolder={vi.fn()}
        serverStatus={offlineStatus}
        isExtracting={false}
        isTransitioning={true}
      />
    );

    expect(screen.getByRole('button', { name: 'Starting Engine' })).toBeDisabled();
    expect(screen.getByText('Starting...')).toBeInTheDocument();

    rerender(
      <TopNavBar
        onToggleServer={vi.fn()}
        onOpenOutputFolder={vi.fn()}
        serverStatus={readyStatus}
        isExtracting={false}
        isTransitioning={true}
      />
    );

    expect(screen.getByRole('button', { name: 'Stopping Engine' })).toBeDisabled();
    expect(screen.getByText('Stopping...')).toBeInTheDocument();
  });

  it('renders Output Folder button and handles click', async () => {
    const user = userEvent.setup();
    const handleOpenOutput = vi.fn();

    render(
      <TopNavBar
        onToggleServer={vi.fn()}
        onOpenOutputFolder={handleOpenOutput}
        serverStatus={readyStatus}
        isExtracting={false}
      />
    );

    const outputFolderBtn = screen.getByRole('button', { name: 'Output Folder' });
    expect(outputFolderBtn).toBeInTheDocument();

    await user.click(outputFolderBtn);
    expect(handleOpenOutput).toHaveBeenCalledTimes(1);
  });
});
