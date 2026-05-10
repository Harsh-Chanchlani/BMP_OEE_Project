import { useEffect, useRef, useState, useCallback } from "react";
import { getToken } from "../api/auth";

const WS_BASE = import.meta.env.VITE_WS_BASE_URL || "ws://localhost:8000";
const RECONNECT_DELAY_MS = 3000;
// Keep last 30 min of raw events — at ~2 events/sec per machine that's ~3600 per machine
const MAX_EVENTS_PER_MACHINE = 4000;

export function useRawOeeWebSocket() {
  const [rawData, setRawData]     = useState([]);
  const [connected, setConnected] = useState(false);
  const wsRef     = useRef(null);
  const timerRef  = useRef(null);
  const unmounted = useRef(false);

  const connect = useCallback(() => {
    if (unmounted.current) return;
    const token = getToken();
    if (!token) {
      timerRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
      return;
    }

    const ws = new WebSocket(`${WS_BASE}/ws/oee_raw`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ token }));
      setConnected(true);
    };

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === "oee_raw_update") {
          // Merge by (machine_id, event_time) — event_time is unique per raw event
          setRawData((prev) => {
            const map = new Map(
              prev.map((r) => [`${r.machine_id}|${r.event_time}`, r])
            );
            for (const r of msg.data) {
              map.set(`${r.machine_id}|${r.event_time}`, r);
            }
            // Trim to avoid unbounded growth — keep most recent per machine
            const all = Array.from(map.values());
            const byMachine = {};
            for (const r of all) {
              if (!byMachine[r.machine_id]) byMachine[r.machine_id] = [];
              byMachine[r.machine_id].push(r);
            }
            const trimmed = [];
            for (const events of Object.values(byMachine)) {
              events.sort((a, b) => new Date(a.event_time) - new Date(b.event_time));
              trimmed.push(...events.slice(-MAX_EVENTS_PER_MACHINE));
            }
            return trimmed;
          });
        }
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

  return { rawData, connected };
}
