import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';

export interface ServerEventsContextValue {
  isConnected: boolean;
  subscribe: <T = any>(eventType: string, handler: (data: T, event: MessageEvent) => void) => () => void;
  addEventListener: (eventType: string, listener: (e: MessageEvent) => void) => void;
  removeEventListener: (eventType: string, listener: (e: MessageEvent) => void) => void;
  eventSource: EventSource | null;
}

const ServerEventsContext = createContext<ServerEventsContextValue | null>(null);

export interface ServerEventsProviderProps {
  children: React.ReactNode;
  eventSource?: any;
}

export const ServerEventsProvider: React.FC<ServerEventsProviderProps> = ({
  children,
  eventSource: customEventSource,
}) => {
  const [isConnected, setIsConnected] = useState(false);
  const listenersRef = useRef<Map<string, Set<(e: MessageEvent) => void>>>(new Map());
  const activeEventSourceRef = useRef<any>(null);

  useEffect(() => {
    let es: any = customEventSource;
    let ownEs = false;

    if (!es && typeof window !== 'undefined' && typeof EventSource !== 'undefined') {
      try {
        es = new EventSource('/api/events');
        ownEs = true;
      } catch (err) {
        console.warn('Failed to initialize EventSource:', err);
      }
    }

    activeEventSourceRef.current = es;
    if (!es) return;

    const handleOpen = () => setIsConnected(true);
    const handleError = () => setIsConnected(false);

    if (es.addEventListener) {
      es.addEventListener('open', handleOpen);
      es.addEventListener('error', handleError);
    } else {
      es.onopen = handleOpen;
      es.onerror = handleError;
    }

    // Attach any listeners registered before EventSource connection
    listenersRef.current.forEach((handlers, eventType) => {
      handlers.forEach((handler) => {
        es.addEventListener?.(eventType, handler);
      });
    });

    return () => {
      if (es.removeEventListener) {
        es.removeEventListener('open', handleOpen);
        es.removeEventListener('error', handleError);
      }
      if (ownEs && es.close) {
        es.close();
      }
      activeEventSourceRef.current = null;
      setIsConnected(false);
    };
  }, [customEventSource]);

  const addEventListener = useCallback((eventType: string, listener: (e: MessageEvent) => void) => {
    let handlers = listenersRef.current.get(eventType);
    if (!handlers) {
      handlers = new Set();
      listenersRef.current.set(eventType, handlers);
    }
    handlers.add(listener);

    const es = activeEventSourceRef.current;
    if (es?.addEventListener) {
      es.addEventListener(eventType, listener);
    }
  }, []);

  const removeEventListener = useCallback((eventType: string, listener: (e: MessageEvent) => void) => {
    const handlers = listenersRef.current.get(eventType);
    if (handlers) {
      handlers.delete(listener);
      if (handlers.size === 0) {
        listenersRef.current.delete(eventType);
      }
    }

    const es = activeEventSourceRef.current;
    if (es?.removeEventListener) {
      es.removeEventListener(eventType, listener);
    }
  }, []);

  const subscribe = useCallback(<T = any>(eventType: string, handler: (data: T, event: MessageEvent) => void) => {
    const listener = (e: MessageEvent) => {
      try {
        const parsed = JSON.parse(e.data);
        handler(parsed, e);
      } catch {
        handler(e.data as unknown as T, e);
      }
    };

    addEventListener(eventType, listener);
    return () => {
      removeEventListener(eventType, listener);
    };
  }, [addEventListener, removeEventListener]);

  const contextValue: ServerEventsContextValue = {
    isConnected,
    subscribe,
    addEventListener,
    removeEventListener,
    eventSource: activeEventSourceRef.current,
  };

  return (
    <ServerEventsContext.Provider value={contextValue}>
      {children}
    </ServerEventsContext.Provider>
  );
};

export function useServerEvents(): ServerEventsContextValue {
  const context = useContext(ServerEventsContext);
  if (!context) {
    // Provide safe fallback if invoked outside Provider (e.g. unit tests without wrapper)
    return {
      isConnected: false,
      subscribe: () => () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      eventSource: null,
    };
  }
  return context;
}
