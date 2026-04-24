import { useEffect, useRef, useState } from "react";
import { getToken } from "../api/auth";

const WS_BASE = import.meta.env.VITE_WS_BASE_URL || "ws://localhost:8000";

export function useOeeWebSocket() {
  const [oeeData, setOeeData]     = useState([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);

  useEffect(() => {
    const token = getToken();
    if (!token) return;

    const ws = new WebSocket(`${WS_BASE}/ws/oee`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ token }));
      setConnected(true);
    };

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === "oee_update") setOeeData(msg.data);
    };

    ws.onclose  = () => setConnected(false);
    ws.onerror  = () => setConnected(false);

    return () => ws.close();
  }, []);

  return { oeeData, connected };
}
