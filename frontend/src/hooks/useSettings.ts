import { useState, useEffect, useCallback, useRef } from 'react';
import { BackendSettings, EngineSettings, ModelStatusInfo } from '../types';
import { INITIAL_SETTINGS } from '../data/mockDocuments';
import { useServerEvents } from '../context/ServerEventsContext';
import { useToast } from './useToast';

export function useSettings(initialUrlState: string | null) {
  const [selectedDpi, setSelectedDpi] = useState<number>(100);
  const [engineSettings, setEngineSettings] = useState<EngineSettings>(() => {
    if (initialUrlState === 'offline') {
      return { ...INITIAL_SETTINGS, status: 'offline' };
    }
    return INITIAL_SETTINGS;
  });
  const [modelStatus, setModelStatus] = useState<ModelStatusInfo | null>(null);
  const { subscribe } = useServerEvents();
  const { toast } = useToast();
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const fetchSettings = useCallback(async () => {
    try {
      const res = await fetch('/api/settings');
      if (res.ok) {
        const data = await res.json();
        if (isMountedRef.current) {
          if (data && typeof data.dpi === 'number') {
            setSelectedDpi(data.dpi);
          }
          setEngineSettings((prev) => ({
            ...prev,
            ...data,
            renderDpi: data?.dpi ?? prev.renderDpi,
          }));
        }
      }
    } catch (err) {
      console.warn('Failed to fetch settings on mount:', err);
    }
  }, []);

  const fetchModelStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/model/status');
      if (res.ok) {
        const data: ModelStatusInfo = await res.json();
        if (isMountedRef.current) {
          setModelStatus(data);
        }
      }
    } catch (err) {
      console.warn('Failed to fetch model status:', err);
    }
  }, []);

  useEffect(() => {
    fetchSettings();
    fetchModelStatus();
  }, [fetchSettings, fetchModelStatus]);

  // Subscribe to SSE model_download_progress events
  useEffect(() => {
    const unsubscribe = subscribe('model_download_progress', (data: any) => {
      const isCompleted = data.status === 'completed' || (!data.is_downloading && (data.percent ?? 0) >= 100);
      setModelStatus((prev) => {
        if (!prev) {
          return {
            repo: data.repo || 'PaddlePaddle/PaddleOCR-VL-1.6-GGUF',
            revision: data.revision || 'main',
            downloaded: isCompleted || data.downloaded === true,
            model_path: data.model_path ?? null,
            mmproj_path: data.mmproj_path ?? null,
            total_bytes: data.total_bytes ?? data.total ?? 0,
            is_downloading: data.is_downloading ?? !isCompleted,
            bytes_downloaded: data.bytes_downloaded ?? data.downloaded ?? 0,
            percent: data.percent ?? 0,
            active_file: data.active_file ?? null,
            error: data.error ?? null,
          };
        }
        return {
          ...prev,
          is_downloading: data.is_downloading ?? !isCompleted,
          bytes_downloaded: data.bytes_downloaded ?? prev.bytes_downloaded,
          percent: data.percent ?? prev.percent,
          active_file: data.active_file ?? prev.active_file,
          downloaded: (isCompleted || data.downloaded === true) ? true : prev.downloaded,
          error: data.error ?? null,
        };
      });
      if (isCompleted) {
        fetchModelStatus();
      }
    });

    return unsubscribe;
  }, [subscribe, fetchModelStatus]);

  const handleDpiChange = useCallback((dpi: number) => {
    const previousDpi = selectedDpi;
    setSelectedDpi(dpi);
    setEngineSettings((prev) => ({
      ...prev,
      dpi,
      renderDpi: dpi,
    }));
    fetch('/api/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dpi }),
    })
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Server returned status ${res.status}`);
        }
      })
      .catch((err) => {
        console.warn('Failed to sync DPI setting to backend:', err);
        if (isMountedRef.current) {
          setSelectedDpi(previousDpi);
          setEngineSettings((prev) => ({
            ...prev,
            dpi: previousDpi,
            renderDpi: previousDpi,
          }));
        }
      });
  }, [selectedDpi]);

  const handleSaveSettings = useCallback((newSettings: BackendSettings) => {
    setEngineSettings((prev) => ({
      ...prev,
      ...newSettings,
      renderDpi: newSettings.dpi ?? prev.renderDpi,
    }));
    if (typeof newSettings.dpi === 'number') {
      setSelectedDpi(newSettings.dpi);
    }
  }, []);

  const handleDownloadModel = useCallback(async () => {
    try {
      setModelStatus((prev) => (prev ? { ...prev, is_downloading: true, error: null } : null));
      const res = await fetch('/api/model/download', { method: 'POST' });
      if (res.ok) {
        await fetchModelStatus();
      } else {
        const body = await res.json().catch(() => ({}));
        const errMsg = body.detail || 'Failed to start model download';
        setModelStatus((prev) =>
          prev ? { ...prev, is_downloading: false, error: errMsg } : null
        );
        toast.error(errMsg);
      }
    } catch (err: any) {
      console.error('Failed to start model download:', err);
      const errMsg = err?.message || 'Network error starting download';
      setModelStatus((prev) =>
        prev ? { ...prev, is_downloading: false, error: errMsg } : null
      );
      toast.error(errMsg);
    }
  }, [fetchModelStatus, toast]);

  const handleCancelModelDownload = useCallback(async () => {
    try {
      const res = await fetch('/api/model/download/cancel', { method: 'POST' });
      if (res.ok) {
        await fetchModelStatus();
      }
    } catch (err) {
      console.error('Failed to cancel model download:', err);
    }
  }, [fetchModelStatus]);

  return {
    selectedDpi,
    setSelectedDpi,
    engineSettings,
    setEngineSettings,
    modelStatus,
    fetchSettings,
    fetchModelStatus,
    handleDpiChange,
    handleSaveSettings,
    handleDownloadModel,
    handleCancelModelDownload,
  };
}
