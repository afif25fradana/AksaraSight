import { useState, useEffect, useMemo, useCallback } from 'react';
import { BackendSettings, DoctorReport, ModelStatusInfo, RuntimeStatusInfo } from '../../types';
import { useServerEvents } from '../../context/ServerEventsContext';

export interface UseSettingsLifecycleProps {
  propRuntimeStatus?: RuntimeStatusInfo | null;
  modelStatus?: ModelStatusInfo | null;
  setFormData: React.Dispatch<React.SetStateAction<BackendSettings>>;
  setSavedSettings: React.Dispatch<React.SetStateAction<BackendSettings | null>>;
  isMountedRef: React.MutableRefObject<boolean>;
}

export function useSettingsLifecycle({
  propRuntimeStatus,
  modelStatus,
  setFormData,
  setSavedSettings,
  isMountedRef,
}: UseSettingsLifecycleProps) {
  const { subscribe } = useServerEvents();
  const [internalModelStatus, setInternalModelStatus] = useState<ModelStatusInfo | null>(null);
  const [internalRuntimeStatus, setInternalRuntimeStatus] = useState<RuntimeStatusInfo | null>(null);
  const [doctorReport, setDoctorReport] = useState<DoctorReport | null>(null);

  const effectiveModelStatus = useMemo(() => {
    if (!modelStatus && !internalModelStatus) return null;
    if (!modelStatus) return internalModelStatus;
    if (!internalModelStatus) return modelStatus;
    return {
      ...internalModelStatus,
      ...modelStatus,
      downloaded: modelStatus.downloaded || internalModelStatus.downloaded,
      is_downloading: modelStatus.is_downloading ?? internalModelStatus.is_downloading,
      percent: modelStatus.percent || internalModelStatus.percent,
      bytes_downloaded: modelStatus.bytes_downloaded || internalModelStatus.bytes_downloaded,
      active_file: modelStatus.active_file || internalModelStatus.active_file,
    };
  }, [modelStatus, internalModelStatus]);

  const effectiveRuntimeStatus = useMemo(() => {
    if (!propRuntimeStatus && !internalRuntimeStatus) return null;
    if (!propRuntimeStatus) return internalRuntimeStatus;
    if (!internalRuntimeStatus) return propRuntimeStatus;
    return {
      ...propRuntimeStatus,
      ...internalRuntimeStatus,
    };
  }, [propRuntimeStatus, internalRuntimeStatus]);

  const fetchRuntimeStatus = useCallback(async () => {
    try {
      const r = await fetch('/api/runtime/status');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      if (isMountedRef.current && d) {
        setInternalRuntimeStatus(d);
      }
      return d;
    } catch (err) {
      console.warn('Could not fetch runtime status:', err);
    }
  }, [isMountedRef]);

  const fetchModelStatus = useCallback(async () => {
    try {
      const r = await fetch('/api/model/status');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      if (isMountedRef.current && d) {
        setInternalModelStatus(d);
      }
      return d;
    } catch (err) {
      console.warn('Could not fetch model status:', err);
    }
  }, [isMountedRef]);

  // Decoupled mount-only effect: fetches settings, doctor report, and initial status once.
  // Incoming SSE ticks and prop updates will NOT re-fetch settings or clobber user form edits.
  useEffect(() => {
    fetch('/api/settings')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => {
        if (isMountedRef.current && d) {
          setFormData((p) => ({ ...p, ...d }));
          setSavedSettings(d);
        }
      })
      .catch((err) => {
        console.warn('Could not fetch settings on mount:', err);
      });

    fetch('/api/doctor')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => {
        if (isMountedRef.current && d?.checks) {
          setDoctorReport(d);
        }
      })
      .catch((err) => {
        console.warn('Could not fetch diagnostic report on mount:', err);
      });

    if (propRuntimeStatus === undefined) {
      fetchRuntimeStatus();
    }

    if (modelStatus === undefined) {
      fetchModelStatus();
    }
  }, []);

  useEffect(() => {
    const unsubRuntime = subscribe('runtime_download_progress', (data: any) => {
      setInternalRuntimeStatus((prev) => ({
        ...prev,
        ...data,
        installed: data.installed ?? prev?.installed ?? false,
        is_downloading: data.is_downloading ?? true,
      }));
    });
    const unsubModel = subscribe('model_download_progress', (data: any) => {
      setInternalModelStatus((prev) => ({
        ...prev,
        ...data,
        downloaded: (data.status === 'completed' || data.downloaded) ? true : prev?.downloaded ?? false,
        is_downloading: data.is_downloading ?? (data.status !== 'completed'),
      }));
    });
    return () => {
      unsubRuntime();
      unsubModel();
    };
  }, [subscribe]);

  return {
    effectiveModelStatus,
    effectiveRuntimeStatus,
    doctorReport,
    setDoctorReport,
    setInternalModelStatus,
    setInternalRuntimeStatus,
    fetchRuntimeStatus,
    fetchModelStatus,
  };
}
