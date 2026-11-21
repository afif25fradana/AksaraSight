import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useVramTelemetry } from '../hooks/useVramTelemetry';
import { VramTelemetry } from '../types';

describe('useVramTelemetry Hook', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      value: false,
    });
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.useRealTimers();
  });

  it('performs initial fetch on mount and populates vram state', async () => {
    const mockTelemetry: VramTelemetry = {
      available: true,
      device_name: 'NVIDIA RTX 4080',
      device_index: 0,
      device_count: 1,
      total_mb: 16384,
      used_mb: 4096,
      free_mb: 12288,
      usage_percent: 25,
      error: null,
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockTelemetry,
    } as Response);

    const { result } = renderHook(() => useVramTelemetry('ready'));

    await waitFor(() => {
      expect(result.current.vram).toEqual(mockTelemetry);
    });

    expect(global.fetch).toHaveBeenCalledWith('/api/hardware/vram');
  });

  it('fails silently without throwing when fetch rejects', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

    const { result } = renderHook(() => useVramTelemetry('offline'));

    // Give microtasks time to settle
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.vram).toBeNull();
  });

  it('bails out on shallow equality to preserve referential stability', async () => {
    const payloadA: VramTelemetry = {
      available: true,
      device_name: 'NVIDIA RTX 4080',
      total_mb: 16384,
      used_mb: 4096,
      usage_percent: 25,
    };

    const payloadB: VramTelemetry = {
      available: true,
      device_name: 'NVIDIA RTX 4080',
      total_mb: 16384,
      used_mb: 4096,
      usage_percent: 25,
    };

    const payloadC: VramTelemetry = {
      available: true,
      device_name: 'NVIDIA RTX 4080',
      total_mb: 16384,
      used_mb: 5120, // changed
      usage_percent: 31,
    };

    let fetchCount = 0;
    global.fetch = vi.fn().mockImplementation(() => {
      fetchCount += 1;
      const data = fetchCount === 1 ? payloadA : fetchCount === 2 ? payloadB : payloadC;
      return Promise.resolve({
        ok: true,
        json: async () => ({ ...data }),
      } as Response);
    });

    const { result } = renderHook(() => useVramTelemetry('ready'));

    await waitFor(() => {
      expect(result.current.vram).not.toBeNull();
    });

    const refAfterFirst = result.current.vram;

    // Second fetch returning identical properties (payloadB)
    await act(async () => {
      await result.current.refreshVram();
    });

    // Referential equality must be preserved via shallowEqualVram bailout
    expect(result.current.vram).toBe(refAfterFirst);

    // Third fetch returning different properties (payloadC)
    await act(async () => {
      await result.current.refreshVram();
    });

    // Reference updates when telemetry changes
    expect(result.current.vram).not.toBe(refAfterFirst);
    expect(result.current.vram?.used_mb).toBe(5120);
  });

  it('pauses polling when document.hidden is true and resumes immediately on visibilitychange', async () => {
    vi.useFakeTimers();

    const mockTelemetry: VramTelemetry = {
      available: true,
      total_mb: 8192,
      used_mb: 2048,
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockTelemetry,
    } as Response);

    const { result } = renderHook(() => useVramTelemetry('ready'));

    // Flush initial fetch
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(global.fetch).toHaveBeenCalledTimes(1);

    // Document becomes hidden
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      value: true,
    });

    // Advance interval by 6s - should NOT fetch because document.hidden is true
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(global.fetch).toHaveBeenCalledTimes(1);

    // Direct refresh attempt while hidden should also bail out
    await act(async () => {
      await result.current.refreshVram();
    });
    expect(global.fetch).toHaveBeenCalledTimes(1);

    // Document becomes visible again
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      value: false,
    });

    // Trigger visibilitychange event
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
      await vi.advanceTimersByTimeAsync(0);
    });

    // Resumed immediately upon visibility change
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  it('cleans up interval, event listener, and prevents state update on unmount', async () => {
    vi.useFakeTimers();
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval');
    const removeEventListenerSpy = vi.spyOn(document, 'removeEventListener');

    let resolveFetch: ((value: any) => void) | null = null;
    global.fetch = vi.fn().mockImplementation(() => {
      return new Promise((resolve) => {
        resolveFetch = resolve;
      });
    });

    const { unmount } = renderHook(() => useVramTelemetry('ready'));

    expect(clearIntervalSpy).not.toHaveBeenCalled();

    unmount();

    expect(clearIntervalSpy).toHaveBeenCalled();
    expect(removeEventListenerSpy).toHaveBeenCalledWith(
      'visibilitychange',
      expect.any(Function)
    );

    // If pending fetch resolves after unmount, it should safely bail out without throwing or updating state
    await act(async () => {
      resolveFetch?.({
        ok: true,
        json: async () => ({ available: true }),
      });
      await vi.advanceTimersByTimeAsync(0);
    });
  });
});
