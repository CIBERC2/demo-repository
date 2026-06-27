import { useEffect, useRef, useCallback } from "react";

export type SSEEvent = {
  topic: string;
  data: Record<string, unknown>;
  ts: number;
};

type Handler = (event: SSEEvent) => void;

const OPERATOR_TOKEN =
  import.meta.env.VITE_OPERATOR_TOKEN ?? "openc2-dev-token";
const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export function useSSE(onEvent: Handler) {
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  const connect = useCallback(() => {
    const es = new EventSource(
      `${API_BASE}/api/stream?token=${OPERATOR_TOKEN}`
    );

    es.onmessage = (e) => {
      try {
        const parsed: SSEEvent = JSON.parse(e.data);
        handlerRef.current(parsed);
      } catch {
        // ignore malformed
      }
    };

    es.onerror = () => {
      es.close();
      setTimeout(connect, 3000);
    };

    return es;
  }, []);

  useEffect(() => {
    const es = connect();
    return () => es.close();
  }, [connect]);
}
