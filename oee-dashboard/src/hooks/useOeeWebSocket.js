import { useEffect, useRef, useState, useCallback } from "react";
import { getToken } from "../api/auth";

const WS_BASE = import.meta.env.VITE_WS_BASE_URL || "ws://localhost:8000";
const RECONNECT_DELAY_MS = 3000;

export function useOeeWebSocket() {
  const [oeeData, setOeeData]     = useState([]);
  const [connected, setConnected] = useState(false);
  const wsRef     = useRef(null);
  const timerRef  = useRef(null);
  const unmounted = useRef(false);

  const connect = useCallback(() => {
    if (unmounted.current) return;
    const token = getToken();
    if (!token) {
      // No token yet — retry after delay
      timerRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
      return;
    }

    const ws = new WebSocket(`${WS_BASE}/ws/oee`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ token }));
      setConnected(true);
    };

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === "oee_update") setOeeData(msg.data);
      } catch (_) {}
    };

    ws.onclose = () => {
      setConnected(false);
      if (!unmounted.current) {
        timerRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
      }
    };

    ws.onerror = () => {
      setConnected(false);
      ws.close();
    };
  }, []);

  useEffect(() => {
    unmounted.current = false;
    connect();
    return () => {
      unmounted.current = true;
      clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { oeeData, connected };
}
