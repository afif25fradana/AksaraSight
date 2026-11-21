import { useState, useEffect, useCallback, useRef } from 'react';
import { VramTelemetry } from '../types';

function shallowEqualVram(prev: VramTelemetry | null, next: VramTelemetry | null): boolean {
  if (prev === next) return true;
  if (!prev || !next) return false;
  return (
    prev.available === next.available &&
    prev.device_name === next.device_name &&
    prev.device_index === next.device_index &&
    prev.device_count === next.device_count &&
    prev.total_mb === next.total_mb &&
    prev.used_mb === next.used_mb &&
    prev.free_mb === next.free_mb &&
    prev.usage_percent === next.usage_percent &&
    prev.error === next.error
  );
}

export function useVramTelemetry(engineStatus?: string) {
  const [vram, setVram] = useState<VramTelemetry | null>(null);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const fetchVram = useCallback(async () => {
    if (typeof document !== 'undefined' && document.hidden) return;
    try {
      const res = await fetch('/api/hardware/vram');
      if (res.ok) {
        const data: VramTelemetry = await res.json();
        if (isMountedRef.current) {
          setVram((prev) => (shallowEqualVram(prev, data) ? prev : data));
        }
      }
    } catch {
      // Non-critical telemetry endpoint: fail silently without bubbling
    }
  }, []);

  // Listen to Page Visibility API: pause polling when hidden, instantly fetch and resume on visible
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (!document.hidden) {
        fetchVram();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [fetchVram]);

  // 6s polling interval + immediate fetch when engineStatus transitions (offline <-> ready)
  useEffect(() => {
    fetchVram();

    const interval = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return;
      fetchVram();
    }, 6000);

    return () => {
      clearInterval(interval);
    };
  }, [fetchVram, engineStatus]);

  return { vram, refreshVram: fetchVram };
}
