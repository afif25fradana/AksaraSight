import React, { createContext, useContext, useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { ToastItem, ToastType } from '../types';

export interface ToastContextValue {
  toasts: ToastItem[];
  addToast: (message: string, type?: ToastType, duration?: number) => string;
  removeToast: (id: string) => void;
  toast: {
    info: (message: string, duration?: number) => string;
    success: (message: string, duration?: number) => string;
    warning: (message: string, duration?: number) => string;
    error: (message: string, duration?: number) => string;
  };
}

const ToastContext = createContext<ToastContextValue | null>(null);

let toastCounter = 0;

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  useEffect(() => {
    return () => {
      timersRef.current.forEach((timer) => clearTimeout(timer));
      timersRef.current.clear();
    };
  }, []);

  const removeToast = useCallback((id: string) => {
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback((message: string, type: ToastType = 'info', duration = 5000) => {
    const id = `toast-${++toastCounter}-${Date.now()}`;
    const newToast: ToastItem = { id, message, type, duration };

    setToasts((prev) => [...prev, newToast]);

    if (duration > 0) {
      const timer = setTimeout(() => {
        timersRef.current.delete(id);
        removeToast(id);
      }, duration);
      timersRef.current.set(id, timer);
    }

    return id;
  }, [removeToast]);

  const toast = useMemo(() => ({
    info: (message: string, duration?: number) => addToast(message, 'info', duration),
    success: (message: string, duration?: number) => addToast(message, 'success', duration),
    warning: (message: string, duration?: number) => addToast(message, 'warning', duration),
    error: (message: string, duration?: number) => addToast(message, 'error', duration),
  }), [addToast]);

  const value = useMemo(() => ({
    toasts,
    addToast,
    removeToast,
    toast,
  }), [toasts, addToast, removeToast, toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
    </ToastContext.Provider>
  );
};

export function useToastContext(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) {
    // Graceful fallback for non-wrapped unit tests
    return {
      toasts: [],
      addToast: () => '',
      removeToast: () => {},
      toast: {
        info: () => '',
        success: () => '',
        warning: () => '',
        error: () => '',
      },
    };
  }
  return context;
}
