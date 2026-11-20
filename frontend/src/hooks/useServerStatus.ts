import { useState, useEffect, useCallback, useRef } from 'react';
import { ServerStatusInfo, VramTelemetry } from '../types';
import { useToast } from './useToast';

export function useServerStatus(runningJobDocId: string | null) {
  const [serverStatus, setServerStatus] = useState<ServerStatusInfo | null>(null);
  const [vram, setVram] = useState<VramTelemetry | null>(null);
  const [isTransitioning, setIsTransitioning] = useState<boolean>(false);
  const { toast } = useToast();
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const fetchServerStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/server/status');
      if (res.ok) {
        const data: ServerStatusInfo = await res.json();
        if (data && data.status && isMountedRef.current) {
          const normalizedStatus = String(data.status).toLowerCase() as 'offline' | 'starting' | 'ready' | 'error';
          const normalizedOwnership = String(data.ownership || 'none').toLowerCase() as 'none' | 'managed' | 'external';
          const normalized: ServerStatusInfo = {
            ...data,
            status: normalizedStatus,
            ownership: normalizedOwnership,
          };
          setServerStatus((prev) => {
            if (
              prev &&
              prev.status === normalized.status &&
              prev.ownership === normalized.ownership &&
              prev.pid === normalized.pid &&
              prev.endpoint === normalized.endpoint
            ) {
              return prev;
            }
            return normalized;
          });
        }
      }
    } catch (err) {
      console.warn('Failed to fetch server status:', err);
    }
  }, []);

  const fetchVram = useCallback(async () => {
    try {
      const res = await fetch('/api/hardware/vram');
      if (res.ok) {
        const data: VramTelemetry = await res.json();
        if (isMountedRef.current) {
          setVram(data);
        }
      }
    } catch {
      // Hardware telemetry query is non-critical; suppress logs
    }
  }, []);

  useEffect(() => {
    fetchServerStatus();
    fetchVram();

    const statusInterval = setInterval(fetchServerStatus, 5000);
    const vramInterval = setInterval(fetchVram, 6000);

    return () => {
      clearInterval(statusInterval);
      clearInterval(vramInterval);
    };
  }, [fetchServerStatus, fetchVram]);

  const handleToggleServer = useCallback(async () => {
    if (isTransitioning) return;
    const isRunning = serverStatus
      ? String(serverStatus.status).toLowerCase() === 'ready'
      : false;

    if (isRunning) {
      if (String(serverStatus?.ownership || '').toLowerCase() === 'external' || runningJobDocId !== null) return;
    }

    setIsTransitioning(true);
    try {
      if (isRunning) {
        const res = await fetch('/api/server/stop', { method: 'POST', signal: AbortSignal.timeout(15000) });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          const errorMsg = errData.detail || errData.error || errData.message || `Failed to stop server (HTTP ${res.status})`;
          toast.error(errorMsg);
        } else {
          toast.info('Local engine stopping...');
        }
      } else {
        const res = await fetch('/api/server/start', { method: 'POST', signal: AbortSignal.timeout(15000) });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          const errorMsg = errData.detail || errData.error || errData.message || `Failed to start server (HTTP ${res.status})`;
          toast.error(errorMsg);
        } else {
          toast.info('Starting local engine...');
        }
      }
      await fetchServerStatus();
      await fetchVram();
    } catch (err: any) {
      console.error('Failed to toggle server state:', err);
      toast.error(err?.message || 'Failed to toggle server state');
    } finally {
      if (isMountedRef.current) {
        setIsTransitioning(false);
      }
    }
  }, [isTransitioning, serverStatus, runningJobDocId, toast, fetchServerStatus, fetchVram]);

  return {
    serverStatus,
    vram,
    isTransitioning,
    fetchServerStatus,
    fetchVram,
    handleToggleServer,
    setServerStatus,
  };
}
