import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SettingsView } from '../components/modals/SettingsView';
import { ServerEventsProvider } from '../context/ServerEventsContext';
import { ToastProvider } from '../context/ToastContext';

describe('SettingsView WAI-ARIA Navigation & Roving Tabindex', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn().mockImplementation((url: string) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/settings')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ dpi: 100, backend: 'llama-cpp' }),
        } as Response);
      }
      if (urlStr.includes('/api/doctor')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ checks: [] }),
        } as Response);
      }
      if (urlStr.includes('/api/runtime/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ installed: true }),
        } as Response);
      }
      if (urlStr.includes('/api/model/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ downloaded: true }),
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
  });

  it('enforces WAI-ARIA roving tabindex (tabIndex=0 for active tab, tabIndex=-1 for inactive)', async () => {
    render(
      <ToastProvider>
        <ServerEventsProvider>
          <SettingsView />
        </ServerEventsProvider>
      </ToastProvider>
    );

    const engineTab = screen.getByRole('tab', { name: /Engine & Hardware/i });
    const processingTab = screen.getByRole('tab', { name: /Processing & Quality/i });
    const advancedTab = screen.getByRole('tab', { name: /Advanced & Network/i });

    // Initial state: 'engine' is active
    expect(engineTab).toHaveAttribute('tabIndex', '0');
    expect(engineTab).toHaveAttribute('aria-selected', 'true');

    expect(processingTab).toHaveAttribute('tabIndex', '-1');
    expect(processingTab).toHaveAttribute('aria-selected', 'false');

    expect(advancedTab).toHaveAttribute('tabIndex', '-1');
    expect(advancedTab).toHaveAttribute('aria-selected', 'false');
  });

  it('navigates categories using ArrowRight, ArrowLeft, Home, and End keys', async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <ServerEventsProvider>
          <SettingsView />
        </ServerEventsProvider>
      </ToastProvider>
    );

    const engineTab = screen.getByRole('tab', { name: /Engine & Hardware/i });
    const processingTab = screen.getByRole('tab', { name: /Processing & Quality/i });
    const advancedTab = screen.getByRole('tab', { name: /Advanced & Network/i });

    // Focus initial active tab
    engineTab.focus();
    expect(document.activeElement).toBe(engineTab);

    // ArrowRight -> switches to processing
    await user.keyboard('{ArrowRight}');
    expect(processingTab).toHaveAttribute('aria-selected', 'true');
    expect(processingTab).toHaveAttribute('tabIndex', '0');
    expect(engineTab).toHaveAttribute('tabIndex', '-1');
    expect(document.activeElement).toBe(processingTab);

    // ArrowRight -> switches to advanced
    await user.keyboard('{ArrowRight}');
    expect(advancedTab).toHaveAttribute('aria-selected', 'true');
    expect(advancedTab).toHaveAttribute('tabIndex', '0');
    expect(processingTab).toHaveAttribute('tabIndex', '-1');
    expect(document.activeElement).toBe(advancedTab);

    // ArrowRight wraps around -> switches to engine
    await user.keyboard('{ArrowRight}');
    expect(engineTab).toHaveAttribute('aria-selected', 'true');
    expect(document.activeElement).toBe(engineTab);

    // ArrowLeft wraps backwards -> switches to advanced
    await user.keyboard('{ArrowLeft}');
    expect(advancedTab).toHaveAttribute('aria-selected', 'true');
    expect(document.activeElement).toBe(advancedTab);

    // Home key -> jumps to first category (engine)
    await user.keyboard('{Home}');
    expect(engineTab).toHaveAttribute('aria-selected', 'true');
    expect(document.activeElement).toBe(engineTab);

    // End key -> jumps to last category (advanced)
    await user.keyboard('{End}');
    expect(advancedTab).toHaveAttribute('aria-selected', 'true');
    expect(document.activeElement).toBe(advancedTab);
  });
});
