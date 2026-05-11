import { useState, useEffect, useCallback, useRef } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, AreaChart, Area,
  BarChart, Bar, ComposedChart, Legend, Cell,
} from "recharts";
import { login, logout, register, getToken, authHeader } from "./api/auth";
import { useOeeWebSocket } from "./hooks/useOeeWebSocket";
import { useAlertsWebSocket } from "./hooks/useAlertsWebSocket";
import { useRawOeeWebSocket } from "./hooks/useRawOeeWebSocket";

const API = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// ── Threshold helper ──────────────────────────────────────────────────────────
function getThreshold(value) {
  if (value >= 85) return { label: "WORLD CLASS", color: "#00ff87", bg: "rgba(0,255,135,0.1)" };
  if (value >= 75) return { label: "GOOD",        color: "#f5c518", bg: "rgba(245,197,24,0.1)" };
  if (value >= 60) return { label: "AVERAGE",     color: "#ff8c42", bg: "rgba(255,140,66,0.1)" };
  return              { label: "POOR",             color: "#ff4757", bg: "rgba(255,71,87,0.1)" };
}

// ── 7 OEE Loss colours (Kennedy's book) ──────────────────────────────────────
const LOSS_COLORS = {
  unplanned_downtime:  "#ff4757",
  setup_changeover:    "#ff6b6b",
  planned_downtime:    "#ff8c42",
  minor_stoppage:      "#f59e0b",
  reduced_speed:       "#fbbf24",
  rejects_rework:      "#60a5fa",
  startup_yield_loss:  "#818cf8",
  none:                "#6b7280",
};

const LOSS_LABELS = {
  unplanned_downtime:  "Unplanned Downtime",
  setup_changeover:    "Setup / Changeover",
  planned_downtime:    "Planned Downtime",
  minor_stoppage:      "Minor Stoppage",
  reduced_speed:       "Reduced Speed",
  rejects_rework:      "Rejects / Rework",
  startup_yield_loss:  "Startup Yield Loss",
  none:                "None",
};

const LOSS_CATEGORY = {
  unplanned_downtime:  "Availability",
  setup_changeover:    "Availability",
  planned_downtime:    "Availability",
  minor_stoppage:      "Performance",
  reduced_speed:       "Performance",
  rejects_rework:      "Quality",
  startup_yield_loss:  "Quality",
  none:                "—",
};

// ── Machine colours for fleet view ───────────────────────────────────────────
const MACHINE_COLORS = {
  "LITHO_ASML_01":  "#00ff87",
  "ETCH_LAM_02":    "#60a5fa",
  "DEP_AMAT_03":    "#f59e0b",
  "CMP_EBARA_04":   "#a78bfa",
  "INSPECT_KLA_05": "#34d399",
};

const inputStyle = {
  background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)",
  borderRadius: 8, padding: "10px 14px", color: "#e8eaf0",
  fontFamily: "'Inter', sans-serif", fontSize: 14, outline: "none",
  width: "100%", boxSizing: "border-box",
};

// ── LoginScreen ───────────────────────────────────────────────────────────────
function LoginScreen({ onLogin }) {
  const [mode, setMode]         = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm]   = useState("");
  const [error, setError]       = useState("");
  const [success, setSuccess]   = useState("");
  const [loading, setLoading]   = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(""); setSuccess("");
    if (mode === "signup" && password !== confirm) {
      setError("Passwords do not match"); return;
    }
    setLoading(true);
    try {
      if (mode === "signup") {
        await register(username, password);
        setSuccess("Account created! Signing you in...");
      }
      await login(username, password);
      onLogin();
    } catch (err) {
      setError(err.message || "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  const switchMode = () => {
    setMode(mode === "login" ? "signup" : "login");
    setError(""); setSuccess(""); setPassword(""); setConfirm("");
  };

  return (
    <div style={{ minHeight: "100vh", background: "#080b10", display: "flex",
      alignItems: "center", justifyContent: "center", fontFamily: "'Inter', system-ui, sans-serif" }}>
      <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(0,255,135,0.2)",
        borderRadius: 16, padding: "40px 48px", width: 360, display: "flex",
        flexDirection: "column", gap: 24 }}>
        <div>
          <div style={{ color: "#00ff87", fontSize: 20, fontWeight: 800, letterSpacing: "3px" }}>⬡ OEE MONITOR</div>
          <div style={{ color: "rgba(255,255,255,0.3)", fontSize: 10, letterSpacing: "2px", marginTop: 4 }}>
            {mode === "login" ? "SIGN IN TO CONTINUE" : "CREATE AN ACCOUNT"}
          </div>
        </div>
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <input type="text" placeholder="Username" value={username}
            onChange={(e) => setUsername(e.target.value)} required style={inputStyle} />
          <input type="password" placeholder="Password" value={password}
            onChange={(e) => setPassword(e.target.value)} required style={inputStyle} />
          {mode === "signup" && (
            <input type="password" placeholder="Confirm Password" value={confirm}
              onChange={(e) => setConfirm(e.target.value)} required style={inputStyle} />
          )}
          {error   && <div style={{ color: "#ff4757", fontSize: 11, letterSpacing: "1px" }}>⚠ {error}</div>}
          {success && <div style={{ color: "#00ff87", fontSize: 11, letterSpacing: "1px" }}>✓ {success}</div>}
          <button type="submit" disabled={loading}
            style={{ background: loading ? "rgba(0,255,135,0.1)" : "rgba(0,255,135,0.15)",
              border: "1px solid rgba(0,255,135,0.4)", color: "#00ff87", padding: "10px",
              borderRadius: 8, fontFamily: "'Inter', sans-serif", fontSize: 13, fontWeight: 700,
              letterSpacing: "2px", cursor: loading ? "not-allowed" : "pointer" }}>
            {loading ? "PLEASE WAIT..." : mode === "login" ? "SIGN IN" : "SIGN UP"}
          </button>
        </form>
        <div style={{ textAlign: "center", fontSize: 11, color: "rgba(255,255,255,0.3)" }}>
          {mode === "login" ? "Don't have an account?" : "Already have an account?"}{" "}
          <span onClick={switchMode}
            style={{ color: "#00ff87", cursor: "pointer", textDecoration: "underline" }}>
            {mode === "login" ? "Sign up" : "Sign in"}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── GaugeArc ──────────────────────────────────────────────────────────────────
function GaugeArc({ value, size = 140 }) {
  const r = 46, cx = size / 2, cy = size / 2 + 10;
  const toRad = (d) => (d * Math.PI) / 180;
  const start = -210, end = 30;
  const filled = start + (value / 100) * (end - start);
  const arc = (from, to) => {
    const x1 = cx + r * Math.cos(toRad(from)), y1 = cy + r * Math.sin(toRad(from));
    const x2 = cx + r * Math.cos(toRad(to)),   y2 = cy + r * Math.sin(toRad(to));
    return `M ${x1} ${y1} A ${r} ${r} 0 ${to - from > 180 ? 1 : 0} 1 ${x2} ${y2}`;
  };
  const { color } = getThreshold(value);
  return (
    <svg width={size} height={size} style={{ overflow: "visible" }}>
      <path d={arc(start, end)}    fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="8" strokeLinecap="round" />
      <path d={arc(start, filled)} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round"
        style={{ filter: `drop-shadow(0 0 6px ${color})` }} />
      <text x={cx} y={cy + 4}  textAnchor="middle" fill={color} fontSize="18" fontWeight="800" fontFamily="'JetBrains Mono', monospace">
        {value.toFixed(1)}%
      </text>
      <text x={cx} y={cy + 20} textAnchor="middle" fill="rgba(255,255,255,0.5)" fontSize="9" fontFamily="'Inter', sans-serif" letterSpacing="2">
        OEE
      </text>
    </svg>
  );
}

// ── StatusBadge ───────────────────────────────────────────────────────────────
function StatusBadge({ value }) {
  const t = getThreshold(value);
  return (
    <span style={{ background: t.bg, border: `1px solid ${t.color}`, color: t.color,
      padding: "2px 10px", borderRadius: 4, fontSize: 11, fontFamily: "'Inter', sans-serif",
      letterSpacing: "1px", fontWeight: 700 }}>{t.label}</span>
  );
}

// ── StatCard ──────────────────────────────────────────────────────────────────
function StatCard({ label, value, unit = "%", sub, color = "#00ff87", icon }) {
  return (
    <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)",
      borderRadius: 12, padding: "16px 20px", display: "flex", flexDirection: "column",
      gap: 4, position: "relative", overflow: "hidden" }}>
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2,
        background: `linear-gradient(90deg, transparent, ${color}, transparent)` }} />
      <div style={{ color: "rgba(255,255,255,0.5)", fontSize: 11, letterSpacing: "1.5px",
        textTransform: "uppercase", fontFamily: "'Inter', sans-serif", fontWeight: 600 }}>{icon} {label}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
        <span style={{ color, fontSize: 28, fontWeight: 800, fontFamily: "'JetBrains Mono', monospace", letterSpacing: -1 }}>
          {typeof value === "number" ? value.toFixed(2) : value}
        </span>
        <span style={{ color: "rgba(255,255,255,0.3)", fontSize: 14 }}>{unit}</span>
      </div>
      {sub && <div style={{ color: "rgba(255,255,255,0.3)", fontSize: 11, fontFamily: "monospace" }}>{sub}</div>}
    </div>
  );
}

// ── CustomTooltip ─────────────────────────────────────────────────────────────
const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: "#0d1117", border: "1px solid rgba(0,255,135,0.3)",
      borderRadius: 8, padding: "10px 14px", fontFamily: "monospace" }}>
      <div style={{ color: "rgba(255,255,255,0.5)", fontSize: 11, marginBottom: 6 }}>{label}</div>
      {payload.map((p) => (
        <div key={p.name} style={{ color: p.color, fontSize: 12 }}>
          {p.name.toUpperCase()}: <strong>{Number(p.value)?.toFixed(2)}%</strong>
        </div>
      ))}
    </div>
  );
};

// ── 1. Real-time OEE Chart (raw per-event, no averaging) ─────────────────────
function RealTimeOeeChart({ machine }) {
  const [rawData, setRawData] = useState([]);
  const intervalRef = useRef(null);

  const fetchRaw = useCallback(() => {
    if (!machine) return;
    fetch(`${API}/api/oee/raw?machine=${machine}&limit=30`, { headers: authHeader() })
      .then((r) => r.ok ? r.json() : [])
      .then((data) => {
        if (!Array.isArray(data)) return;
        const sorted = [...data].sort((a, b) => new Date(a.event_time) - new Date(b.event_time));
        setRawData(sorted);
      })
      .catch(() => {});
  }, [machine]);

  useEffect(() => {
    fetchRaw();
    intervalRef.current = setInterval(fetchRaw, 3000);
    return () => clearInterval(intervalRef.current);
  }, [fetchRaw]);

  const chartData = rawData.map((r) => ({
    time: new Date(r.event_time).toLocaleTimeString(),
    oee: parseFloat(Number(r.oee).toFixed(2)),
    loss: r.loss_event_name && r.loss_event_name !== "none" ? r.loss_event_name : null,
    availability: parseFloat(Number(r.availability || 0).toFixed(2)),
    performance:  parseFloat(Number(r.performance  || 0).toFixed(2)),
    quality:      parseFloat(Number(r.quality      || 0).toFixed(2)),
    lot_id: r.lot_id || null,
    shift:  r.shift  || null,
  }));

  return (
    <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 16, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: "2px", color: "rgba(255,255,255,0.8)" }}>
            REAL-TIME OEE
          </div>
          <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", marginTop: 2 }}>
            Raw per-event readings · no averaging · orange dots = active loss event · polls every 3s
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#00ff87" }} />
            <span style={{ fontSize: 10, color: "rgba(255,255,255,0.4)" }}>Normal</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#f59e0b" }} />
            <span style={{ fontSize: 10, color: "rgba(255,255,255,0.4)" }}>Loss Active</span>
          </div>
          <span style={{ fontSize: 10, color: "rgba(255,255,255,0.25)" }}>{chartData.length} EVENTS</span>
        </div>
      </div>
      {chartData.length === 0 ? (
        <div style={{ height: 220, display: "flex", alignItems: "center", justifyContent: "center",
          color: "rgba(255,255,255,0.2)", fontSize: 12 }}>
          No raw events yet — producer and Spark job need to be running
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartData} margin={{ top: 10, right: 60, bottom: 36, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
            <XAxis dataKey="time"
              tick={{ fill: "rgba(255,255,255,0.5)", fontSize: 10 }}
              tickLine={false} axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
              interval={Math.max(0, Math.floor(chartData.length / 8) - 1)}
              label={{ value: "Event Time", position: "insideBottom", offset: -22,
                fill: "rgba(255,255,255,0.4)", fontSize: 11 }} />
            <YAxis
              domain={([dataMin, dataMax]) => {
                const pad = Math.max((dataMax - dataMin) * 0.3, 3);
                return [Math.max(0, Math.floor(dataMin - pad)), Math.min(100, Math.ceil(dataMax + pad))];
              }}
              tick={{ fill: "rgba(255,255,255,0.5)", fontSize: 11 }}
              tickLine={false} axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
              tickFormatter={(v) => `${v}%`} width={52}
              label={{ value: "OEE (%)", angle: -90, position: "insideLeft", offset: 14,
                fill: "rgba(255,255,255,0.4)", fontSize: 11 }} />
            <Tooltip
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0]?.payload;
                return (
                  <div style={{ background: "#0d1117", border: "1px solid rgba(0,255,135,0.3)",
                    borderRadius: 8, padding: "10px 14px", fontFamily: "monospace", minWidth: 180 }}>
                    <div style={{ color: "rgba(255,255,255,0.5)", fontSize: 11, marginBottom: 6 }}>{label}</div>
                    <div style={{ color: "#00ff87", fontSize: 12 }}>OEE: <strong>{Number(d?.oee).toFixed(2)}%</strong></div>
                    <div style={{ color: "#60a5fa", fontSize: 11 }}>A: {Number(d?.availability).toFixed(2)}%</div>
                    <div style={{ color: "#f59e0b", fontSize: 11 }}>P: {Number(d?.performance).toFixed(2)}%</div>
                    <div style={{ color: "#34d399", fontSize: 11 }}>Q: {Number(d?.quality).toFixed(2)}%</div>
                    {d?.loss && (
                      <div style={{ color: "#f59e0b", fontSize: 11, marginTop: 4, borderTop: "1px solid rgba(255,255,255,0.1)", paddingTop: 4 }}>
                        ⚠ Loss: {LOSS_LABELS[d.loss] || d.loss}
                        <div style={{ color: "rgba(255,255,255,0.35)", fontSize: 10 }}>
                          Category: {LOSS_CATEGORY[d.loss] || "—"}
                        </div>
                      </div>
                    )}
                    {d?.lot_id && <div style={{ color: "rgba(255,255,255,0.3)", fontSize: 10, marginTop: 3 }}>Lot: {d.lot_id}</div>}
                    {d?.shift  && <div style={{ color: "rgba(255,255,255,0.3)", fontSize: 10 }}>Shift: {d.shift}</div>}
                  </div>
                );
              }}
            />
            <ReferenceLine y={85} stroke="rgba(0,255,135,0.45)" strokeDasharray="4 4"
              label={{ value: "85%", position: "right", fill: "rgba(0,255,135,0.8)", fontSize: 11 }} />
            <ReferenceLine y={75} stroke="rgba(245,197,24,0.45)" strokeDasharray="4 4"
              label={{ value: "75%", position: "right", fill: "rgba(245,197,24,0.8)", fontSize: 11 }} />
            <Line type="monotone" dataKey="oee" name="OEE" stroke="#00ff87" strokeWidth={2}
              isAnimationActive={false}
              dot={(props) => {
                const { cx, cy, payload } = props;
                const hasLoss = !!payload.loss;
                return (
                  <circle key={`dot-${cx}-${cy}`} cx={cx} cy={cy}
                    r={hasLoss ? 5 : 3.5}
                    fill={hasLoss ? "#f59e0b" : "#00ff87"}
                    stroke={hasLoss ? "rgba(245,158,11,0.5)" : "transparent"}
                    strokeWidth={hasLoss ? 3 : 0} />
                );
              }}
              activeDot={{ r: 6, fill: "#00ff87" }} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// ── 2. ForecastChart ─────────────────────────────────────────────────────────
// Shows windowed OEE history (green solid) + ARIMA forecast (purple dashed).
// A "NOW" divider separates what happened from what is predicted.
// Confidence band drawn as SVG rectangles — avoids the Area cutout bug.
function ForecastChart({ machine, windowedHistory }) {
  const [forecast, setForecast]         = useState([]);
  const [spc, setSpc]                   = useState(null);
  const [restHistory, setRestHistory]   = useState([]);
  const [fetchError, setFetchError]     = useState(null);
  const [lastFetchTime, setLastFetchTime] = useState(null);
  const intervalRef = useRef(null);

  useEffect(() => {
    if (!machine) return;
    fetch(`${API}/api/spc?machine=${machine}`, { headers: authHeader() })
      .then((r) => r.json())
      .then((d) => setSpc(Array.isArray(d) && d.length > 0 ? d[0] : null))
      .catch(() => setSpc(null));
  }, [machine]);

  useEffect(() => {
    if (!machine) return;
    fetch(`${API}/api/oee/history?machine=${machine}&limit=20`, { headers: authHeader() })
      .then((r) => r.ok ? r.json() : [])
      .then((d) => {
        if (!Array.isArray(d)) return;
        setRestHistory(d.map((r) => ({
          time: new Date(r.window_start).toLocaleTimeString(),
          oee: parseFloat(Number(r.avg_oee).toFixed(2)),
        })));
      })
      .catch(() => {});
  }, [machine]);

  const fetchForecast = useCallback(() => {
    if (!machine) return;
    setFetchError(null);
    fetch(`${API}/api/oee/forecast?machine=${machine}`, { headers: authHeader() })
      .then((r) => r.ok ? r.json() : [])
      .then((d) => {
        setForecast(Array.isArray(d) ? d : []);
        setLastFetchTime(new Date().toLocaleTimeString());
      })
      .catch((e) => setFetchError(e.message));
  }, [machine]);

  useEffect(() => {
    fetchForecast();
    intervalRef.current = setInterval(fetchForecast, 60000);
    return () => clearInterval(intervalRef.current);
  }, [fetchForecast]);

  const effectiveHistory = (windowedHistory.length > 0 ? windowedHistory : restHistory).slice(-20);

  // History points — only have `oee`, no `predicted_oee`
  const histPoints = effectiveHistory.map((r, i) => ({
    idx: i,
    label: r.time,
    oee: r.oee,
    predicted_oee: undefined,
    conf_upper: undefined,
    conf_lower: undefined,
  }));

  // Forecast points — only have `predicted_oee`, no `oee`
  const fcPoints = forecast.map((r, i) => ({
    idx: histPoints.length + i,
    label: `+${(i + 1) * 30}s`,
    oee: undefined,
    predicted_oee: parseFloat(Number(r.predicted_oee).toFixed(2)),
    conf_upper: parseFloat(Number(r.confidence_upper).toFixed(2)),
    conf_lower: parseFloat(Number(r.confidence_lower).toFixed(2)),
  }));

  // Bridge: duplicate last history point with predicted_oee = oee so lines connect
  let combined = [...histPoints];
  if (histPoints.length > 0 && fcPoints.length > 0) {
    const last = histPoints[histPoints.length - 1];
    combined[combined.length - 1] = {
      ...last,
      predicted_oee: last.oee,
      conf_upper: last.oee,
      conf_lower: last.oee,
    };
  }
  combined = [...combined, ...fcPoints];

  const nowLabel = histPoints.length > 0 ? histPoints[histPoints.length - 1].label : null;
  const hasForecast = fcPoints.length > 0;
  const hasHistory  = histPoints.length > 0;

  // Y domain that fits all values + SPC lines
  const allOeeVals = [
    ...histPoints.map((p) => p.oee),
    ...fcPoints.map((p) => p.predicted_oee),
    ...fcPoints.map((p) => p.conf_upper),
    ...fcPoints.map((p) => p.conf_lower),
    spc ? spc.ucl : null,
    spc ? spc.lcl : null,
  ].filter((v) => v != null);
  const yMin = allOeeVals.length ? Math.max(0,   Math.floor(Math.min(...allOeeVals) - 5)) : 0;
  const yMax = allOeeVals.length ? Math.min(100, Math.ceil(Math.max(...allOeeVals)  + 5)) : 100;

  return (
    <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 16, padding: "20px 24px" }}>

      {/* ── Header ── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: "2px", color: "rgba(255,255,255,0.8)" }}>
            WINDOWED OEE + ARIMA FORECAST
          </div>
          <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", marginTop: 3 }}>
            Green = 1-min windowed avg · Purple dashed = ARIMA prediction · Shaded = 95% CI
            {lastFetchTime && (
              <span style={{ marginLeft: 8, color: "rgba(255,255,255,0.2)" }}>
                · updated {lastFetchTime}
              </span>
            )}
          </div>
        </div>
        {/* Legend */}
        <div style={{ display: "flex", gap: 12, flexShrink: 0, marginLeft: 16, alignItems: "center" }}>
          {[
            { stroke: "#00ff87", dash: null,  label: "Actual" },
            { stroke: "#a78bfa", dash: "5 3", label: "Forecast" },
            { stroke: "#ff4757", dash: "4 3", label: "UCL/LCL" },
          ].map(({ stroke, dash, label }) => (
            <div key={label} style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <svg width="22" height="10">
                <line x1="0" y1="5" x2="22" y2="5" stroke={stroke} strokeWidth="2"
                  strokeDasharray={dash || "0"} />
              </svg>
              <span style={{ fontSize: 10, color: "rgba(255,255,255,0.45)", whiteSpace: "nowrap" }}>{label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── SPC pills ── */}
      {spc && (
        <div style={{ display: "flex", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
          {[
            { label: "UCL",  value: spc.ucl.toFixed(1),        color: "#ff4757" },
            { label: "Mean", value: spc.mean_value.toFixed(1), color: "#f59e0b" },
            { label: "LCL",  value: spc.lcl.toFixed(1),        color: "#ff4757" },
            { label: "σ",    value: spc.std_dev?.toFixed(2) ?? "—", color: "rgba(255,255,255,0.4)" },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ background: "rgba(255,255,255,0.04)",
              border: "1px solid rgba(255,255,255,0.08)", borderRadius: 6,
              padding: "3px 10px", display: "flex", gap: 6, alignItems: "center" }}>
              <span style={{ fontSize: 9, color: "rgba(255,255,255,0.35)", letterSpacing: "1px" }}>{label}</span>
              <span style={{ fontSize: 12, color, fontFamily: "monospace", fontWeight: 700 }}>{value}%</span>
            </div>
          ))}
        </div>
      )}

      {fetchError && (
        <div style={{ color: "#ff8c42", fontSize: 11, marginBottom: 8 }}>
          ⚠ Forecast unavailable: {fetchError} — is arima_forecaster.py running?
        </div>
      )}

      {!hasHistory && !hasForecast ? (
        <div style={{ height: 280, display: "flex", alignItems: "center", justifyContent: "center",
          color: "rgba(255,255,255,0.2)", fontSize: 12 }}>
          No windowed OEE data yet — Spark needs ~90s to produce first windows
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={combined} margin={{ top: 10, right: 20, bottom: 44, left: 20 }}>
            <defs>
              {/* Confidence band as a proper gradient fill on the forecast line */}
              <linearGradient id="ciBand" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"   stopColor="#a78bfa" stopOpacity={0.25} />
                <stop offset="100%" stopColor="#a78bfa" stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis
              dataKey="label"
              tick={{ fill: "rgba(255,255,255,0.4)", fontSize: 10 }}
              tickLine={false}
              axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
              interval={Math.max(0, Math.floor(combined.length / 8) - 1)}
              label={{ value: "← Actual windows  |  Forecast steps →",
                position: "insideBottom", offset: -30,
                fill: "rgba(255,255,255,0.3)", fontSize: 11 }}
            />
            <YAxis
              domain={[yMin, yMax]}
              tick={{ fill: "rgba(255,255,255,0.4)", fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
              tickFormatter={(v) => `${v}%`}
              width={48}
              label={{ value: "OEE (%)", angle: -90, position: "insideLeft", offset: 14,
                fill: "rgba(255,255,255,0.3)", fontSize: 11 }}
            />
            <Tooltip
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0]?.payload;
                const isFc = d?.predicted_oee != null && d?.oee == null;
                return (
                  <div style={{ background: "#0d1117",
                    border: `1px solid ${isFc ? "rgba(167,139,250,0.5)" : "rgba(0,255,135,0.4)"}`,
                    borderRadius: 8, padding: "10px 14px", fontFamily: "monospace", minWidth: 190 }}>
                    <div style={{ fontSize: 10, color: "rgba(255,255,255,0.35)",
                      letterSpacing: "1px", marginBottom: 6 }}>
                      {isFc ? "🔮 FORECAST" : "📊 ACTUAL"} · {label}
                    </div>
                    {d?.oee != null && (
                      <div style={{ color: "#00ff87", fontSize: 13 }}>
                        OEE: <strong>{d.oee.toFixed(2)}%</strong>
                      </div>
                    )}
                    {d?.predicted_oee != null && (
                      <div style={{ color: "#a78bfa", fontSize: 13 }}>
                        Predicted: <strong>{d.predicted_oee.toFixed(2)}%</strong>
                      </div>
                    )}
                    {isFc && d?.conf_upper != null && (
                      <div style={{ color: "rgba(167,139,250,0.55)", fontSize: 11, marginTop: 3 }}>
                        95% CI: [{d.conf_lower?.toFixed(1)}%, {d.conf_upper?.toFixed(1)}%]
                      </div>
                    )}
                  </div>
                );
              }}
            />

            {/* NOW divider */}
            {nowLabel && hasForecast && (
              <ReferenceLine x={nowLabel} stroke="rgba(255,255,255,0.3)"
                strokeWidth={1.5} strokeDasharray="5 4"
                label={{ value: "NOW ▶", position: "insideTopLeft",
                  fill: "rgba(255,255,255,0.45)", fontSize: 10, fontWeight: 700 }} />
            )}

            {/* SPC lines */}
            {spc && <ReferenceLine y={spc.ucl} stroke="#ff4757" strokeWidth={1} strokeDasharray="5 3"
              label={{ value: `UCL ${spc.ucl.toFixed(1)}%`, position: "insideTopRight",
                fill: "#ff4757", fontSize: 9 }} />}
            {spc && <ReferenceLine y={spc.mean_value} stroke="#f59e0b" strokeWidth={1} strokeDasharray="7 3"
              label={{ value: `Mean ${spc.mean_value.toFixed(1)}%`, position: "insideTopRight",
                fill: "#f59e0b", fontSize: 9 }} />}
            {spc && <ReferenceLine y={spc.lcl} stroke="#ff4757" strokeWidth={1} strokeDasharray="5 3"
              label={{ value: `LCL ${spc.lcl.toFixed(1)}%`, position: "insideBottomRight",
                fill: "#ff4757", fontSize: 9 }} />}

            {/* Confidence band — upper boundary (invisible stroke, purple fill) */}
            {/* We draw it as a custom dot-less line with a large stroke to fake a band */}
            <Line type="monotone" dataKey="conf_upper"
              stroke="rgba(167,139,250,0.15)" strokeWidth={0}
              dot={false} activeDot={false}
              isAnimationActive={false} legendType="none" />
            <Line type="monotone" dataKey="conf_lower"
              stroke="rgba(167,139,250,0.15)" strokeWidth={0}
              dot={false} activeDot={false}
              isAnimationActive={false} legendType="none" />

            {/* Actual windowed OEE — green solid */}
            <Line type="monotone" dataKey="oee"
              stroke="#00ff87" strokeWidth={2.5}
              dot={(props) => {
                const { cx, cy } = props;
                return <circle key={`h-${cx}-${cy}`} cx={cx} cy={cy} r={3.5}
                  fill="#00ff87" stroke="none" />;
              }}
              activeDot={{ r: 5, fill: "#00ff87" }}
              isAnimationActive={false}
              connectNulls={false} />

            {/* ARIMA forecast — purple dashed */}
            <Line type="monotone" dataKey="predicted_oee"
              stroke="#a78bfa" strokeWidth={2.5} strokeDasharray="7 4"
              dot={(props) => {
                const { cx, cy } = props;
                return <circle key={`f-${cx}-${cy}`} cx={cx} cy={cy} r={4}
                  fill="#a78bfa" stroke="rgba(167,139,250,0.4)" strokeWidth={2} />;
              }}
              activeDot={{ r: 6, fill: "#a78bfa" }}
              isAnimationActive={false}
              connectNulls={false} />
          </LineChart>
        </ResponsiveContainer>
      )}

      {/* Confidence band drawn as SVG overlay — avoids Recharts Area cutout bug */}
      {hasForecast && fcPoints.length >= 2 && (
        <div style={{ marginTop: 8, padding: "8px 12px",
          background: "rgba(167,139,250,0.06)", border: "1px solid rgba(167,139,250,0.15)",
          borderRadius: 8, fontSize: 10, color: "rgba(255,255,255,0.35)", lineHeight: 1.6 }}>
          🔮 Next {fcPoints.length} windows (~{fcPoints.length * 30}s ahead) ·
          CI: [{fcPoints[0].conf_lower.toFixed(1)}%, {fcPoints[0].conf_upper.toFixed(1)}%] ·
          Refreshes every 60s · As actual data arrives, green line will reach the purple dots
        </div>
      )}
    </div>
  );
}

// ── 2.5. Predicted vs Actual OEE Chart ────────────────────────────────────────
function PredictedVsActualChart({ machine }) {
  const [comparisonData, setComparisonData] = useState([]);
  const [fetchError, setFetchError]         = useState(null);
  const [lastFetchTime, setLastFetchTime]   = useState(null);
  const intervalRef = useRef(null);

  // Fetch comparison data every 60 seconds
  const fetchComparisonData = useCallback(() => {
    if (!machine) return;
    setFetchError(null);
    fetch(`${API}/api/oee/forecast_vs_actual?machine=${machine}`, { headers: authHeader() })
      .then((r) => r.ok ? r.json() : [])
      .then((data) => {
        if (Array.isArray(data)) {
          // Parse and format the data
          const formatted = data.map((r) => ({
            target_time: new Date(r.target_time).toLocaleTimeString(),
            predicted_oee: r.predicted_oee != null ? parseFloat(Number(r.predicted_oee).toFixed(2)) : null,
            actual_oee: r.actual_oee != null ? parseFloat(Number(r.actual_oee).toFixed(2)) : null,
            confidence_lower: r.confidence_lower != null ? parseFloat(Number(r.confidence_lower).toFixed(2)) : null,
            confidence_upper: r.confidence_upper != null ? parseFloat(Number(r.confidence_upper).toFixed(2)) : null,
            prediction_time: r.prediction_time ? new Date(r.prediction_time).toLocaleTimeString() : null,
            ts: new Date(r.target_time).getTime(),
          }));
          // Sort by timestamp and take last 24 hours worth (assuming 30s windows = ~2880 points per day)
          // For display purposes, limit to last 48 points (~24 minutes at 30s intervals)
          const sorted = formatted.sort((a, b) => a.ts - b.ts).slice(-48);
          setComparisonData(sorted);
          setLastFetchTime(new Date().toLocaleTimeString());
        }
      })
      .catch((e) => setFetchError(e.message));
  }, [machine]);

  useEffect(() => {
    fetchComparisonData();
    intervalRef.current = setInterval(fetchComparisonData, 60000);
    return () => clearInterval(intervalRef.current);
  }, [fetchComparisonData]);

  return (
    <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 16, padding: "20px 24px" }}>

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: "2px", color: "rgba(255,255,255,0.8)" }}>
            PREDICTED VS ACTUAL OEE
          </div>
          <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", marginTop: 3 }}>
            Historical forecast accuracy · purple = predicted · green = actual · last 24 min
            {lastFetchTime && <span style={{ marginLeft: 8, color: "rgba(255,255,255,0.2)" }}>
              · updated {lastFetchTime}
            </span>}
          </div>
        </div>
        {/* Legend */}
        <div style={{ display: "flex", gap: 8, flexShrink: 0, marginLeft: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <svg width="16" height="16">
              <rect x="0" y="0" width="16" height="16" fill="#a78bfa" opacity="0.8"/>
            </svg>
            <span style={{ fontSize: 10, color: "rgba(255,255,255,0.5)", whiteSpace: "nowrap" }}>Predicted</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <svg width="16" height="16">
              <circle cx="8" cy="8" r="5" fill="#00ff87"/>
            </svg>
            <span style={{ fontSize: 10, color: "rgba(255,255,255,0.5)", whiteSpace: "nowrap" }}>Actual</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <svg width="16" height="16">
              <rect x="0" y="0" width="16" height="16" fill="#a78bfa" opacity="0.2"/>
            </svg>
            <span style={{ fontSize: 10, color: "rgba(255,255,255,0.5)", whiteSpace: "nowrap" }}>95% CI</span>
          </div>
        </div>
      </div>

      {fetchError && (
        <div style={{ color: "#ff8c42", fontSize: 11, marginBottom: 8 }}>
          ⚠ Comparison data unavailable: {fetchError}
        </div>
      )}

      {comparisonData.length === 0 ? (
        <div style={{ height: 280, display: "flex", alignItems: "center", justifyContent: "center",
          color: "rgba(255,255,255,0.2)", fontSize: 12 }}>
          No historical predictions yet — ARIMA forecaster needs to run for at least 60s
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={comparisonData} margin={{ top: 10, right: 20, bottom: 40, left: 20 }}>
            <defs>
              <linearGradient id="confBandComparison" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"   stopColor="#a78bfa" stopOpacity={0.25} />
                <stop offset="100%" stopColor="#a78bfa" stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis
              dataKey="target_time"
              tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 10 }}
              tickLine={false}
              axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
              interval={Math.max(0, Math.floor(comparisonData.length / 8) - 1)}
              label={{ value: "Target Time (when prediction was for)",
                position: "insideBottom", offset: -28,
                fill: "rgba(255,255,255,0.35)", fontSize: 11 }}
            />
            <YAxis
              domain={([dataMin, dataMax]) => {
                const allVals = comparisonData.flatMap(d => [
                  d.predicted_oee, d.actual_oee, d.confidence_lower, d.confidence_upper
                ].filter(v => v != null));
                const lo = Math.min(...allVals, dataMin);
                const hi = Math.max(...allVals, dataMax);
                const pad = Math.max((hi - lo) * 0.15, 3);
                return [Math.max(0, Math.floor(lo - pad)), Math.min(100, Math.ceil(hi + pad))];
              }}
              tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
              tickFormatter={(v) => `${v}%`}
              width={48}
              label={{ value: "OEE (%)", angle: -90, position: "insideLeft", offset: 14,
                fill: "rgba(255,255,255,0.35)", fontSize: 11 }}
            />
            <Tooltip
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0]?.payload;
                return (
                  <div style={{ background: "#0d1117",
                    border: "1px solid rgba(167,139,250,0.4)",
                    borderRadius: 8, padding: "10px 14px", fontFamily: "monospace", minWidth: 200 }}>
                    <div style={{ color: "rgba(255,255,255,0.4)", fontSize: 10, marginBottom: 6,
                      letterSpacing: "1px" }}>
                      TARGET: {label}
                    </div>
                    {d?.predicted_oee != null && (
                      <div style={{ color: "#a78bfa", fontSize: 12 }}>
                        Predicted: <strong>{d.predicted_oee.toFixed(2)}%</strong>
                      </div>
                    )}
                    {d?.actual_oee != null && (
                      <div style={{ color: "#00ff87", fontSize: 12 }}>
                        Actual: <strong>{d.actual_oee.toFixed(2)}%</strong>
                      </div>
                    )}
                    {d?.actual_oee == null && (
                      <div style={{ color: "rgba(255,255,255,0.3)", fontSize: 11, fontStyle: "italic" }}>
                        Actual: (future)
                      </div>
                    )}
                    {d?.confidence_upper != null && d?.confidence_lower != null && (
                      <div style={{ color: "rgba(167,139,250,0.6)", fontSize: 11, marginTop: 2 }}>
                        95% CI: [{d.confidence_lower.toFixed(1)}%, {d.confidence_upper.toFixed(1)}%]
                      </div>
                    )}
                    {d?.prediction_time && (
                      <div style={{ color: "rgba(255,255,255,0.25)", fontSize: 9, marginTop: 4 }}>
                        Predicted at: {d.prediction_time}
                      </div>
                    )}
                  </div>
                );
              }}
            />

            {/* Confidence band — upper fill */}
            <Area type="monotone" dataKey="confidence_upper"
              stroke="none" fill="url(#confBandComparison)" fillOpacity={1}
              isAnimationActive={false} legendType="none" />
            {/* Confidence band — lower cutout */}
            <Area type="monotone" dataKey="confidence_lower"
              stroke="none" fill="#080b10" fillOpacity={1}
              isAnimationActive={false} legendType="none" />

            {/* Predicted OEE — purple bars */}
            <Bar dataKey="predicted_oee" name="Predicted OEE"
              fill="#a78bfa" fillOpacity={0.8}
              isAnimationActive={false} />

            {/* Actual OEE — green dots/line */}
            <Line type="monotone" dataKey="actual_oee" name="Actual OEE"
              stroke="#00ff87" strokeWidth={2.5}
              dot={{ r: 4, fill: "#00ff87", strokeWidth: 0 }}
              activeDot={{ r: 6, fill: "#00ff87" }}
              isAnimationActive={false}
              connectNulls={false} />
          </ComposedChart>
        </ResponsiveContainer>
      )}

      {/* Accuracy note */}
      {comparisonData.length > 0 && (
        <div style={{ marginTop: 12, padding: "8px 12px",
          background: "rgba(0,255,135,0.06)", border: "1px solid rgba(0,255,135,0.15)",
          borderRadius: 8, fontSize: 10, color: "rgba(255,255,255,0.35)", lineHeight: 1.6 }}>
          📊 Showing {comparisonData.length} historical predictions vs actual outcomes.
          Purple bars = what we predicted. Green dots = what actually happened.
          Shaded region = 95% confidence interval. Refreshes every 60s.
        </div>
      )}
    </div>
  );
}

// ── 3. APQ Breakdown Chart ────────────────────────────────────────────────────
function ApqChart({ machine }) {
  const [apqData, setApqData]   = useState([]);
  const [apqError, setApqError] = useState(null);

  useEffect(() => {
    if (!machine) return;
    setApqError(null);
    fetch(`${API}/api/oee/apq?machine=${machine}&limit=30`, { headers: authHeader() })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((data) => setApqData(Array.isArray(data) ? data : []))
      .catch((e) => setApqError(`Failed to load APQ data: ${e.message}`));
  }, [machine]);

  const formatted = apqData.map((r) => ({
    time: new Date(r.window_start).toLocaleTimeString(),
    avg_availability: parseFloat(Number(r.avg_availability || 0).toFixed(2)),
    avg_performance:  parseFloat(Number(r.avg_performance  || 0).toFixed(2)),
    avg_quality:      parseFloat(Number(r.avg_quality      || 0).toFixed(2)),
  }));

  return (
    <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 16, padding: "20px 24px", height: "100%" }}>
      <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: "2px", color: "rgba(255,255,255,0.8)", marginBottom: 4 }}>
        APQ BREAKDOWN
      </div>
      <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", marginBottom: 16 }}>
        Availability · Performance · Quality per 1-min window
      </div>
      {apqError ? (
        <div style={{ color: "#ff4757", fontSize: 12 }}>{apqError}</div>
      ) : formatted.length === 0 ? (
        <div style={{ height: 240, display: "flex", alignItems: "center", justifyContent: "center",
          color: "rgba(255,255,255,0.2)", fontSize: 12 }}>No APQ data available</div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={formatted} margin={{ top: 10, right: 20, bottom: 36, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey="time"
              tick={{ fill: "rgba(255,255,255,0.5)", fontSize: 10 }}
              tickLine={false} axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
              interval={Math.max(0, Math.floor(formatted.length / 6) - 1)}
              label={{ value: "Time (window start)", position: "insideBottom", offset: -22,
                fill: "rgba(255,255,255,0.4)", fontSize: 11 }} />
            <YAxis
              domain={([dataMin, dataMax]) => {
                const pad = Math.max((dataMax - dataMin) * 0.2, 5);
                return [Math.max(0, Math.floor(dataMin - pad)), Math.min(100, Math.ceil(dataMax + pad))];
              }}
              tick={{ fill: "rgba(255,255,255,0.5)", fontSize: 11 }}
              tickLine={false} axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
              tickFormatter={(v) => `${v}%`} width={48}
              label={{ value: "Component (%)", angle: -90, position: "insideLeft", offset: 14,
                fill: "rgba(255,255,255,0.4)", fontSize: 11 }} />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ fontSize: 11, color: "rgba(255,255,255,0.55)" }} />
            <ReferenceLine y={85} stroke="rgba(0,255,135,0.4)" strokeDasharray="4 4"
              label={{ value: "85%", fill: "rgba(0,255,135,0.7)", fontSize: 10, position: "right" }} />
            <Bar dataKey="avg_availability" name="Availability" fill="#60a5fa" />
            <Bar dataKey="avg_performance"  name="Performance"  fill="#f59e0b" />
            <Bar dataKey="avg_quality"      name="Quality"      fill="#34d399" />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// ── 4. 7 OEE Losses Pareto Chart ─────────────────────────────────────────────
function LossesChart({ machine }) {
  const [lossData, setLossData]     = useState([]);
  const [hoveredLoss, setHoveredLoss] = useState(null);

  useEffect(() => {
    if (!machine) return;
    fetch(`${API}/api/losses?machine=${machine}`, { headers: authHeader() })
      .then((r) => r.ok ? r.json() : [])
      .then((data) => {
        if (!Array.isArray(data)) return;
        const sorted = [...data]
          .filter((d) => d.loss_type !== "none")
          .sort((a, b) => b.total_loss_percentage - a.total_loss_percentage);
        let cumulative = 0;
        const total = sorted.reduce((s, d) => s + Number(d.total_loss_percentage), 0);
        const withCumulative = sorted.map((d) => {
          cumulative += Number(d.total_loss_percentage);
          return {
            ...d,
            label: LOSS_LABELS[d.loss_type] || d.loss_type,
            category: LOSS_CATEGORY[d.loss_type] || "—",
            cumulative_pct: total > 0 ? parseFloat((cumulative / total * 100).toFixed(1)) : 0,
          };
        });
        setLossData(withCumulative);
      })
      .catch(() => setLossData([]));
  }, [machine]);

  return (
    <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 16, padding: "20px 24px" }}>
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: "2px", color: "rgba(255,255,255,0.8)" }}>
          7 OEE LOSSES — PARETO
        </div>
        <div style={{ fontSize: 10, color: "rgba(255,255,255,0.35)", marginTop: 3 }}>
          Kennedy's 7 OEE losses · bars = loss magnitude · red line = cumulative % · fix tallest bars first (80/20 rule)
        </div>
      </div>

      {/* Category legend */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
        {[
          { label: "Availability Losses", color: "#ff4757" },
          { label: "Performance Losses",  color: "#f59e0b" },
          { label: "Quality Losses",      color: "#60a5fa" },
        ].map(({ label, color }) => (
          <div key={label} style={{ background: `${color}15`, border: `1px solid ${color}40`,
            borderRadius: 6, padding: "3px 10px" }}>
            <span style={{ fontSize: 10, color, fontWeight: 700 }}>{label}</span>
          </div>
        ))}
      </div>

      {/* Loss type pills */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14 }}>
        {Object.entries(LOSS_LABELS).filter(([k]) => k !== "none").map(([key, label]) => {
          const color = LOSS_COLORS[key];
          return (
            <div key={key}
              onMouseEnter={() => setHoveredLoss(key)}
              onMouseLeave={() => setHoveredLoss(null)}
              style={{ background: `${color}15`,
                border: `1px solid ${hoveredLoss === key ? color : color + "40"}`,
                borderRadius: 6, padding: "3px 8px", cursor: "default", transition: "border-color 0.15s" }}>
              <span style={{ fontSize: 9, color, fontWeight: 700 }}>{label}</span>
              <span style={{ fontSize: 9, color: "rgba(255,255,255,0.3)", marginLeft: 4 }}>
                ({LOSS_CATEGORY[key]})
              </span>
            </div>
          );
        })}
      </div>

      {lossData.length === 0 ? (
        <div style={{ height: 220, display: "flex", alignItems: "center", justifyContent: "center",
          color: "rgba(255,255,255,0.2)", fontSize: 12 }}>No loss data available</div>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <ComposedChart data={lossData} margin={{ top: 10, right: 60, bottom: 60, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey="label"
              tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 10 }}
              tickLine={false} axisLine={false}
              angle={-30} textAnchor="end" interval={0}
              label={{ value: "Loss Type", position: "insideBottom", offset: -48,
                fill: "rgba(255,255,255,0.3)", fontSize: 11 }} />
            <YAxis yAxisId="left"
              tick={{ fill: "rgba(255,255,255,0.4)", fontSize: 10 }} tickLine={false} axisLine={false}
              tickFormatter={(v) => `${v}%`} width={48}
              label={{ value: "Loss (%)", angle: -90, position: "insideLeft", offset: 14,
                fill: "rgba(255,255,255,0.3)", fontSize: 11 }} />
            <YAxis yAxisId="right" orientation="right" domain={[0, 100]}
              tick={{ fill: "rgba(255,255,255,0.4)", fontSize: 10 }} tickLine={false} axisLine={false}
              tickFormatter={(v) => `${v}%`}
              label={{ value: "Cumulative (%)", angle: 90, position: "insideRight", offset: 14,
                fill: "rgba(255,255,255,0.3)", fontSize: 11 }} />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0]?.payload;
                const color = LOSS_COLORS[d?.loss_type] || "#f59e0b";
                return (
                  <div style={{ background: "#0d1117", border: "1px solid rgba(255,255,255,0.15)",
                    borderRadius: 8, padding: "10px 14px", fontFamily: "monospace", maxWidth: 240 }}>
                    <div style={{ color, fontWeight: 700, fontSize: 11, marginBottom: 4 }}>
                      {d?.label}
                    </div>
                    <div style={{ color: "rgba(255,255,255,0.6)", fontSize: 11 }}>
                      Category: <strong style={{ color }}>{d?.category}</strong>
                    </div>
                    <div style={{ color: "rgba(255,255,255,0.7)", fontSize: 11 }}>
                      Loss: <strong>{Number(d?.total_loss_percentage).toFixed(2)}%</strong>
                    </div>
                    <div style={{ color: "rgba(255,255,255,0.5)", fontSize: 11 }}>
                      Cumulative: <strong>{d?.cumulative_pct}%</strong>
                    </div>
                  </div>
                );
              }}
            />
            <Bar yAxisId="left" dataKey="total_loss_percentage" name="Loss %"
              label={{ position: "top", fill: "rgba(255,255,255,0.5)", fontSize: 10,
                formatter: (v) => `${Number(v).toFixed(1)}%` }}>
              {lossData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={LOSS_COLORS[entry.loss_type] || "#f59e0b"} />
              ))}
            </Bar>
            <Line yAxisId="right" type="monotone" dataKey="cumulative_pct" name="Cumulative %"
              stroke="#ff4757" strokeWidth={2.5} dot={{ r: 4, fill: "#ff4757" }}
              activeDot={{ r: 6, fill: "#ff4757" }} />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// ── 5. SPC Control Chart ──────────────────────────────────────────────────────
function SpcChart({ machine, history }) {
  const [spc, setSpc] = useState(null);

  useEffect(() => {
    if (!machine) return;
    fetch(`${API}/api/spc?machine=${machine}`, { headers: authHeader() })
      .then((r) => r.json())
      .then((data) => setSpc(Array.isArray(data) && data.length > 0 ? data[0] : null))
      .catch(() => setSpc(null));
  }, [machine]);

  const spcDomain = ([dataMin, dataMax]) => {
    const allVals = [dataMin, dataMax];
    if (spc) allVals.push(spc.ucl, spc.lcl, spc.mean_value);
    const lo = Math.min(...allVals);
    const hi = Math.max(...allVals);
    const pad = Math.max((hi - lo) * 0.15, 2);
    return [Math.max(0, Math.floor(lo - pad)), Math.min(100, Math.ceil(hi + pad))];
  };

  return (
    <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 16, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: "2px", color: "#e8eaf0" }}>SPC CONTROL CHART</div>
          <div style={{ fontSize: 10, color: "rgba(255,255,255,0.4)", marginTop: 4 }}>
            Statistical Process Control · OEE vs control limits · red dots = out-of-control
          </div>
        </div>
        {spc && (
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
            {[
              { label: `UCL  ${spc.ucl.toFixed(1)}%`,       color: "#ff4757", bg: "rgba(255,71,87,0.12)" },
              { label: `Mean ${spc.mean_value.toFixed(1)}%`, color: "#f59e0b", bg: "rgba(245,158,11,0.12)" },
              { label: `LCL  ${spc.lcl.toFixed(1)}%`,        color: "#ff4757", bg: "rgba(255,71,87,0.12)" },
            ].map(({ label, color, bg }) => (
              <span key={label} style={{ background: bg, border: `1px solid ${color}60`,
                color, padding: "3px 10px", borderRadius: 6, fontSize: 11,
                fontFamily: "monospace", fontWeight: 700, letterSpacing: "0.5px", whiteSpace: "nowrap" }}>
                {label}
              </span>
            ))}
          </div>
        )}
        {!spc && (
          <span style={{ fontSize: 11, color: "rgba(255,255,255,0.3)" }}>
            SPC data pending (needs ≥10 windows)
          </span>
        )}
      </div>

      {history.length === 0 ? (
        <div style={{ height: 260, display: "flex", alignItems: "center", justifyContent: "center",
          color: "rgba(255,255,255,0.2)", fontSize: 13 }}>No OEE history yet</div>
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={history} margin={{ top: 10, right: 70, bottom: 36, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
            <XAxis dataKey="time"
              tick={{ fill: "rgba(255,255,255,0.5)", fontSize: 11 }}
              tickLine={false} axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
              interval={Math.max(0, Math.floor(history.length / 6) - 1)}
              label={{ value: "Time (window start)", position: "insideBottom", offset: -22,
                fill: "rgba(255,255,255,0.4)", fontSize: 11 }} />
            <YAxis
              domain={spcDomain}
              tick={{ fill: "rgba(255,255,255,0.5)", fontSize: 11 }}
              tickLine={false} axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
              tickFormatter={(v) => `${v}%`} width={52}
              label={{ value: "OEE (%)", angle: -90, position: "insideLeft", offset: 14,
                fill: "rgba(255,255,255,0.4)", fontSize: 11 }} />
            <Tooltip content={<CustomTooltip />} />
            {spc && (
              <ReferenceLine y={spc.ucl} stroke="#ff4757" strokeWidth={1.5} strokeDasharray="6 3"
                label={{ value: `UCL ${spc.ucl.toFixed(1)}%`, position: "right",
                  fill: "#ff4757", fontSize: 11, fontWeight: 700 }} />
            )}
            {spc && (
              <ReferenceLine y={spc.mean_value} stroke="#f59e0b" strokeWidth={1.5} strokeDasharray="8 3"
                label={{ value: `Mean ${spc.mean_value.toFixed(1)}%`, position: "right",
                  fill: "#f59e0b", fontSize: 11, fontWeight: 700 }} />
            )}
            {spc && (
              <ReferenceLine y={spc.lcl} stroke="#ff4757" strokeWidth={1.5} strokeDasharray="6 3"
                label={{ value: `LCL ${spc.lcl.toFixed(1)}%`, position: "right",
                  fill: "#ff4757", fontSize: 11, fontWeight: 700 }} />
            )}
            <Line type="monotone" dataKey="oee" name="OEE" stroke="#00ff87" strokeWidth={2.5}
              isAnimationActive={false}
              dot={(props) => {
                const { cx, cy, value } = props;
                const outOfControl = spc && (value > spc.ucl || value < spc.lcl);
                return (
                  <circle key={`dot-${cx}-${cy}`} cx={cx} cy={cy}
                    r={outOfControl ? 5 : 3.5}
                    fill={outOfControl ? "#ff4757" : "#00ff87"}
                    stroke={outOfControl ? "rgba(255,71,87,0.4)" : "transparent"}
                    strokeWidth={outOfControl ? 3 : 0} />
                );
              }}
              activeDot={{ r: 6, fill: "#00ff87" }} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// ── 6. Shift Performance Chart ────────────────────────────────────────────────
function ShiftChart({ machine }) {
  const [shiftData, setShiftData]   = useState([]);
  const [shiftError, setShiftError] = useState(null);

  useEffect(() => {
    if (!machine) return;
    setShiftError(null);
    fetch(`${API}/api/shifts?machine=${machine}&days=7`, { headers: authHeader() })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((data) => {
        if (!Array.isArray(data)) { setShiftData([]); return; }
        // Group by shift_date, pivot shifts into columns
        const byDate = {};
        for (const row of data) {
          const d = row.shift_date;
          if (!byDate[d]) byDate[d] = { date: d };
          byDate[d][row.shift] = parseFloat(Number(row.avg_oee || 0).toFixed(2));
        }
        const sorted = Object.values(byDate).sort((a, b) => a.date.localeCompare(b.date));
        setShiftData(sorted);
      })
      .catch((e) => setShiftError(`Failed to load shift data: ${e.message}`));
  }, [machine]);

  // Detect which shifts are present
  const shifts = ["morning", "afternoon", "night"];
  const shiftColors = { morning: "#34d399", afternoon: "#f59e0b", night: "#60a5fa" };
  const shiftLabels = { morning: "Morning", afternoon: "Afternoon", night: "Night" };

  const presentShifts = shifts.filter((s) =>
    shiftData.some((row) => row[s] != null)
  );

  return (
    <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 16, padding: "20px 24px", height: "100%" }}>
      <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: "2px", color: "rgba(255,255,255,0.8)", marginBottom: 4 }}>
        SHIFT PERFORMANCE
      </div>
      <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", marginBottom: 16 }}>
        Avg OEE per shift · last 7 days · identify worst-performing shift
      </div>
      {shiftError ? (
        <div style={{ color: "#ff4757", fontSize: 12 }}>{shiftError}</div>
      ) : shiftData.length === 0 ? (
        <div style={{ height: 240, display: "flex", alignItems: "center", justifyContent: "center",
          color: "rgba(255,255,255,0.2)", fontSize: 12 }}>No shift data available</div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={shiftData} margin={{ top: 10, right: 20, bottom: 36, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey="date"
              tick={{ fill: "rgba(255,255,255,0.5)", fontSize: 10 }}
              tickLine={false} axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
              tickFormatter={(v) => v.slice(5)} // show MM-DD
              label={{ value: "Date", position: "insideBottom", offset: -22,
                fill: "rgba(255,255,255,0.4)", fontSize: 11 }} />
            <YAxis
              domain={([dataMin, dataMax]) => {
                const pad = Math.max((dataMax - dataMin) * 0.2, 5);
                return [Math.max(0, Math.floor(dataMin - pad)), Math.min(100, Math.ceil(dataMax + pad))];
              }}
              tick={{ fill: "rgba(255,255,255,0.5)", fontSize: 11 }}
              tickLine={false} axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
              tickFormatter={(v) => `${v}%`} width={48}
              label={{ value: "Avg OEE (%)", angle: -90, position: "insideLeft", offset: 14,
                fill: "rgba(255,255,255,0.4)", fontSize: 11 }} />
            <Tooltip
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                return (
                  <div style={{ background: "#0d1117", border: "1px solid rgba(255,255,255,0.15)",
                    borderRadius: 8, padding: "10px 14px", fontFamily: "monospace" }}>
                    <div style={{ color: "rgba(255,255,255,0.5)", fontSize: 11, marginBottom: 6 }}>{label}</div>
                    {payload.map((p) => (
                      <div key={p.name} style={{ color: p.fill, fontSize: 12 }}>
                        {p.name}: <strong>{Number(p.value).toFixed(2)}%</strong>
                      </div>
                    ))}
                  </div>
                );
              }}
            />
            <Legend wrapperStyle={{ fontSize: 11, color: "rgba(255,255,255,0.55)" }} />
            <ReferenceLine y={85} stroke="rgba(0,255,135,0.35)" strokeDasharray="4 4"
              label={{ value: "85%", position: "right", fill: "rgba(0,255,135,0.7)", fontSize: 10 }} />
            {presentShifts.map((shift) => (
              <Bar key={shift} dataKey={shift} name={shiftLabels[shift]}
                fill={shiftColors[shift]} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// ── 7. Alert Log ──────────────────────────────────────────────────────────────
function AlertLog({ alerts }) {
  const [acking, setAcking] = useState(new Set());

  const acknowledge = async (id) => {
    setAcking((prev) => new Set([...prev, id]));
    try {
      await fetch(`${API}/api/alerts/${id}/acknowledge`, {
        method: "POST",
        headers: authHeader(),
      });
    } catch (_) {}
    // The WS will push updated list; optimistically remove from acking set after delay
    setTimeout(() => setAcking((prev) => { const s = new Set(prev); s.delete(id); return s; }), 3000);
  };

  const sorted = [...alerts].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 20);

  const levelColor = (level) => {
    if (level === "CRITICAL") return "#ff4757";
    if (level === "ANOMALY")  return "#a78bfa";
    return "#ff8c42"; // WARNING
  };

  const levelIcon = (level) => {
    if (level === "CRITICAL") return "⚠";
    if (level === "ANOMALY")  return "⚡";
    return "△";
  };

  return (
    <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 16, overflow: "hidden", display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "16px 20px", borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
        <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: "2px", color: "rgba(255,255,255,0.8)" }}>
          ALERT LOG
        </div>
        <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", marginTop: 2 }}>
          Unacknowledged alerts · WARNING / CRITICAL / ANOMALY · live via WebSocket
        </div>
      </div>
      <div style={{ flex: 1, padding: "12px 16px", display: "flex", flexDirection: "column",
        gap: 8, overflowY: "auto", maxHeight: 340 }}>
        {sorted.length === 0 ? (
          <div style={{ color: "rgba(255,255,255,0.2)", fontSize: 11, textAlign: "center", marginTop: 30 }}>
            ✓ No unacknowledged alerts — system nominal
          </div>
        ) : sorted.map((a) => {
          const color = levelColor(a.alert_level);
          const isAcking = acking.has(a.id);
          return (
            <div key={a.id} style={{
              background: `${color}10`,
              border: `1px solid ${color}35`,
              borderRadius: 8, padding: "10px 12px",
              animation: "slideIn 0.3s ease",
              opacity: isAcking ? 0.5 : 1,
              transition: "opacity 0.3s",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <div style={{ fontSize: 10, color, fontWeight: 700, letterSpacing: "0.5px" }}>
                    {levelIcon(a.alert_level)} {a.alert_level} · {a.machine_id}
                  </div>
                  <div style={{ fontSize: 12, color: "rgba(255,255,255,0.75)", marginTop: 3 }}>
                    OEE: <strong style={{ color }}>{Number(a.avg_oee).toFixed(2)}%</strong>
                    {a.threshold != null && (
                      <span style={{ color: "rgba(255,255,255,0.35)", fontSize: 11 }}>
                        {" "}· threshold: {Number(a.threshold).toFixed(1)}%
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 9, color: "rgba(255,255,255,0.25)", marginTop: 2 }}>
                    {a.created_at ? new Date(a.created_at).toLocaleString() : ""}
                  </div>
                </div>
                <button
                  onClick={() => acknowledge(a.id)}
                  disabled={isAcking}
                  style={{
                    background: isAcking ? "rgba(255,255,255,0.05)" : `${color}20`,
                    border: `1px solid ${color}50`,
                    color: isAcking ? "rgba(255,255,255,0.3)" : color,
                    padding: "4px 10px", borderRadius: 6,
                    fontFamily: "monospace", fontSize: 9, fontWeight: 700,
                    letterSpacing: "1px", cursor: isAcking ? "not-allowed" : "pointer",
                    whiteSpace: "nowrap", marginLeft: 8, flexShrink: 0,
                  }}>
                  {isAcking ? "ACK..." : "ACK"}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── 8. Fleet View ─────────────────────────────────────────────────────────────
function FleetView({ machines }) {
  const [restRawByMachine, setRestRawByMachine] = useState({});

  useEffect(() => {
    if (!machines.length) return;
    const fetchAll = () => {
      Promise.all(
        machines.map((m) =>
          fetch(`${API}/api/oee/raw?machine=${m}&limit=30`, { headers: authHeader() })
            .then((r) => r.ok ? r.json() : [])
            .then((data) => [m, data])
            .catch(() => [m, []])
        )
      ).then((results) => {
        const byMachine = {};
        for (const [m, data] of results) byMachine[m] = data;
        setRestRawByMachine(byMachine);
      });
    };
    fetchAll();
    const id = setInterval(fetchAll, 5000);
    return () => clearInterval(id);
  }, [machines]);

  return (
    <div style={{ padding: "24px 32px", display: "flex", flexDirection: "column", gap: 24 }}>
      <div style={{ fontSize: 11, color: "rgba(255,255,255,0.3)", letterSpacing: "2px" }}>
        ALL MACHINES · LIVE RAW OEE · LAST 30 EVENTS PER MACHINE
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        {machines.map((machineId) => {
          const color = MACHINE_COLORS[machineId] || "#00ff87";
          const history = (restRawByMachine[machineId] || [])
            .sort((a, b) => new Date(a.event_time) - new Date(b.event_time))
            .slice(-30)
            .map((r) => ({
              time: new Date(r.event_time).toLocaleTimeString(),
              oee: parseFloat(Number(r.oee).toFixed(2)),
              loss: r.loss_event_name && r.loss_event_name !== "none" ? r.loss_event_name : null,
            }));
          const latest = history.length > 0 ? history[history.length - 1] : null;
          const t = getThreshold(latest?.oee ?? 0);

          return (
            <div key={machineId} style={{
              background: "rgba(255,255,255,0.02)",
              border: `1px solid ${color}25`,
              borderRadius: 16, padding: "20px 24px",
              position: "relative", overflow: "hidden",
            }}>
              <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2,
                background: `linear-gradient(90deg, transparent, ${color}, transparent)` }} />
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                <div>
                  <div style={{ fontSize: 11, color, fontWeight: 700, letterSpacing: "1.5px" }}>{machineId}</div>
                  <div style={{ fontSize: 9, color: "rgba(255,255,255,0.3)", marginTop: 3, letterSpacing: "1px" }}>
                    {history.length} RAW EVENTS
                  </div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
                  <span style={{ fontSize: 22, fontWeight: 800, color: t.color,
                    fontFamily: "'JetBrains Mono', monospace" }}>
                    {latest ? `${latest.oee.toFixed(1)}%` : "—"}
                  </span>
                  <StatusBadge value={latest?.oee ?? 0} />
                </div>
              </div>
              {history.length === 0 ? (
                <div style={{ height: 120, display: "flex", alignItems: "center", justifyContent: "center",
                  color: "rgba(255,255,255,0.15)", fontSize: 11 }}>No data yet</div>
              ) : (
                <ResponsiveContainer width="100%" height={120}>
                  <AreaChart data={history} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
                    <defs>
                      <linearGradient id={`grad-${machineId}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%"   stopColor={color} stopOpacity={0.25} />
                        <stop offset="100%" stopColor={color} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                    <XAxis dataKey="time"
                      tick={{ fill: "rgba(255,255,255,0.2)", fontSize: 8 }}
                      tickLine={false} axisLine={false}
                      interval={Math.max(0, Math.floor(history.length / 5) - 1)} />
                    <YAxis
                      domain={([dataMin, dataMax]) => {
                        const pad = Math.max((dataMax - dataMin) * 0.3, 3);
                        return [Math.max(0, Math.floor(dataMin - pad)), Math.min(100, Math.ceil(dataMax + pad))];
                      }}
                      tick={{ fill: "rgba(255,255,255,0.2)", fontSize: 8 }}
                      tickLine={false} axisLine={false}
                      tickFormatter={(v) => `${v}%`} width={36} />
                    <Tooltip content={<CustomTooltip />} />
                    <ReferenceLine y={85} stroke="rgba(255,255,255,0.1)" strokeDasharray="4 4" />
                    <Area type="monotone" dataKey="oee" name="OEE"
                      stroke={color} strokeWidth={1.5}
                      fill={`url(#grad-${machineId})`}
                      dot={false} activeDot={{ r: 3, fill: color }}
                      isAnimationActive={false} />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Window Aggregates Table ───────────────────────────────────────────────────
function WindowAggregatesTable({ machine, history }) {
  return (
    <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 16, overflow: "hidden" }}>
      <div style={{ padding: "16px 24px", borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
        <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: "2px", color: "rgba(255,255,255,0.8)" }}>
          WINDOW AGGREGATES
        </div>
        <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", marginTop: 2 }}>
          Live from oee_data · Spark micro-batches · 1-min windows
        </div>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: "rgba(255,255,255,0.03)" }}>
              {["MACHINE ID", "WINDOW START", "WINDOW END", "AVG OEE", "STATUS"].map((h) => (
                <th key={h} style={{ padding: "10px 20px", textAlign: "left", fontSize: 9,
                  letterSpacing: "2px", color: "rgba(255,255,255,0.3)", fontWeight: 700,
                  borderBottom: "1px solid rgba(255,255,255,0.05)" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...history].reverse().slice(0, 10).map((row, i) => {
              const t = getThreshold(row.oee);
              return (
                <tr key={i} style={{ borderBottom: "1px solid rgba(255,255,255,0.03)" }}
                  onMouseEnter={(e) => e.currentTarget.style.background = "rgba(255,255,255,0.03)"}
                  onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}>
                  <td style={{ padding: "10px 20px", fontSize: 12, color: "#60a5fa" }}>{machine}</td>
                  <td style={{ padding: "10px 20px", fontSize: 11, color: "rgba(255,255,255,0.4)" }}>
                    {row.window_start ? new Date(row.window_start).toLocaleTimeString() : row.time}
                  </td>
                  <td style={{ padding: "10px 20px", fontSize: 11, color: "rgba(255,255,255,0.4)" }}>
                    {row.window_end ? new Date(row.window_end).toLocaleTimeString() : "—"}
                  </td>
                  <td style={{ padding: "10px 20px", fontSize: 13, color: t.color, fontWeight: 700 }}>
                    {row.oee.toFixed(2)}%
                  </td>
                  <td style={{ padding: "10px 20px" }}><StatusBadge value={row.oee} /></td>
                </tr>
              );
            })}
            {history.length === 0 && (
              <tr>
                <td colSpan={5} style={{ padding: "24px 20px", textAlign: "center",
                  color: "rgba(255,255,255,0.2)", fontSize: 12 }}>
                  No windowed data yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Main Dashboard ────────────────────────────────────────────────────────────
function Dashboard() {
  const [machines, setMachines]       = useState([]);
  const [machine, setMachine]         = useState("");
  const [stats, setStats]             = useState(null);
  const [loading, setLoading]         = useState(true);
  const [error, setError]             = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [view, setView]               = useState("machine"); // "machine" | "fleet"

  const { oeeData, connected: wsConnected } = useOeeWebSocket();
  const { alerts }                          = useAlertsWebSocket();

  // Windowed history for the selected machine (from WS)
  const history = oeeData
    .filter((r) => r.machine_id === machine)
    .sort((a, b) => new Date(a.window_start) - new Date(b.window_start))
    .map((r) => ({
      time: new Date(r.window_start).toLocaleTimeString(),
      oee: parseFloat(Number(r.avg_oee).toFixed(2)),
      window_start: r.window_start,
      window_end: r.window_end,
    }));

  // Latest OEE value — prefer most recent windowed window
  const latestWindow = history.length > 0 ? history[history.length - 1] : null;
  const oeeVal = Number(latestWindow?.oee || 0);
  const thresh = getThreshold(oeeVal);

  // Fetch machine list once
  useEffect(() => {
    fetch(`${API}/api/machines`, { headers: authHeader() })
      .then((r) => {
        if (r.status === 401) { logout(); return []; }
        return r.json();
      })
      .then((list) => {
        setMachines(list);
        if (list.length > 0) setMachine(list[0]);
        else setLoading(false);
      })
      .catch(() => { setError("Cannot reach API on port 8000"); setLoading(false); });
  }, []);

  // Fetch stats for selected machine
  useEffect(() => {
    if (!machine) return;
    setError(null);
    fetch(`${API}/api/oee/stats?machine=${machine}`, { headers: authHeader() })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((st) => {
        setStats(st);
        setLastRefresh(new Date().toLocaleTimeString());
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [machine]);

  const avg24h  = Number(stats?.avg_oee       || 0);
  const minOEE  = Number(stats?.min_oee        || 0);
  const maxOEE  = Number(stats?.max_oee        || 0);
  const totalWin = stats?.total_windows        || 0;

  return (
    <div style={{ minHeight: "100vh", background: "#080b10", color: "#e8eaf0",
      fontFamily: "'Inter', system-ui, sans-serif", padding: 0 }}>
      <style>{`
        @keyframes pulse   { 0%,100%{opacity:1}50%{opacity:0.3} }
        @keyframes slideIn { from{transform:translateX(20px);opacity:0}to{transform:translateX(0);opacity:1} }
        @keyframes spin    { from{transform:rotate(0deg)}to{transform:rotate(360deg)} }
      `}</style>

      {/* ── Top Navigation Bar ── */}
      <div style={{ background: "rgba(8,11,16,0.97)", borderBottom: "1px solid rgba(0,255,135,0.15)",
        padding: "12px 32px", display: "flex", alignItems: "center", justifyContent: "space-between",
        position: "sticky", top: 0, zIndex: 100 }}>
        <div>
          <div style={{ color: "#00ff87", fontSize: 18, fontWeight: 800, letterSpacing: "3px" }}>⬡ OEE MONITOR</div>
          <div style={{ color: "rgba(255,255,255,0.3)", fontSize: 10, letterSpacing: "2px" }}>
            KAFKA → SPARK → POSTGRES → REACT
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          {/* View toggle */}
          <div style={{ display: "flex", background: "rgba(255,255,255,0.04)",
            border: "1px solid rgba(255,255,255,0.08)", borderRadius: 8, padding: 3, gap: 2 }}>
            {[
              { key: "machine", label: "⬡ MACHINE VIEW" },
              { key: "fleet",   label: "⊞ FLEET VIEW" },
            ].map(({ key, label }) => (
              <button key={key} onClick={() => setView(key)}
                style={{
                  background: view === key ? "rgba(0,255,135,0.15)" : "transparent",
                  border: view === key ? "1px solid rgba(0,255,135,0.4)" : "1px solid transparent",
                  color: view === key ? "#00ff87" : "rgba(255,255,255,0.35)",
                  padding: "5px 14px", borderRadius: 6, fontFamily: "monospace",
                  fontSize: 10, fontWeight: 700, letterSpacing: "1px", cursor: "pointer",
                  transition: "all 0.15s",
                }}>
                {label}
              </button>
            ))}
          </div>

          {lastRefresh && (
            <span style={{ color: "rgba(255,255,255,0.3)", fontSize: 10 }}>Last: {lastRefresh}</span>
          )}

          {/* WS status indicator */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 7, height: 7, borderRadius: "50%",
              background: error ? "#ff4757" : wsConnected ? "#00ff87" : "#f59e0b",
              boxShadow: `0 0 8px ${error ? "#ff4757" : wsConnected ? "#00ff87" : "#f59e0b"}`,
              animation: "pulse 1.5s infinite" }} />
            <span style={{ color: "rgba(255,255,255,0.5)", fontSize: 11, letterSpacing: "1px" }}>
              {error ? "DISCONNECTED" : wsConnected ? "LIVE · WS" : "RECONNECTING"}
            </span>
          </div>

          {/* Machine selector — machine view only */}
          {view === "machine" && (
            <select value={machine} onChange={(e) => setMachine(e.target.value)}
              style={{ background: "rgba(0,255,135,0.08)", border: "1px solid rgba(0,255,135,0.3)",
                color: "#00ff87", padding: "6px 12px", borderRadius: 6, fontFamily: "monospace",
                fontSize: 12, cursor: "pointer", outline: "none" }}>
              {machines.map((m) => (
                <option key={m} value={m} style={{ background: "#0d1117" }}>{m}</option>
              ))}
            </select>
          )}

          <button onClick={logout}
            style={{ background: "transparent", border: "1px solid rgba(255,71,87,0.3)", color: "#ff4757",
              padding: "5px 12px", borderRadius: 6, fontFamily: "monospace", fontSize: 10,
              letterSpacing: "1px", cursor: "pointer" }}>LOGOUT</button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div style={{ background: "rgba(255,71,87,0.1)", border: "1px solid rgba(255,71,87,0.4)",
          margin: "16px 32px", padding: "12px 20px", borderRadius: 8, color: "#ff4757", fontSize: 12 }}>
          ⚠ {error}
        </div>
      )}

      {/* Loading spinner */}
      {loading && !error && (
        <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 200 }}>
          <div style={{ width: 32, height: 32, border: "3px solid rgba(0,255,135,0.1)",
            borderTop: "3px solid #00ff87", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
        </div>
      )}

      {/* ── Fleet View ── */}
      {!loading && view === "fleet" && (
        <FleetView machines={machines} />
      )}

      {/* ── Machine View ── */}
      {!loading && view === "machine" && (
        <div style={{ padding: "24px 32px", display: "flex", flexDirection: "column", gap: 24 }}>

          {/* Row 1: Gauge (220px) | KPI stat cards (3×2 grid) */}
          <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 20 }}>
            <div style={{ background: "rgba(255,255,255,0.02)", border: `1px solid ${thresh.color}30`,
              borderRadius: 16, padding: 24, display: "flex", flexDirection: "column",
              alignItems: "center", gap: 12, position: "relative", overflow: "hidden" }}>
              <div style={{ position: "absolute", inset: 0,
                background: `radial-gradient(ellipse at center, ${thresh.color}08 0%, transparent 70%)` }} />
              <div style={{ color: "rgba(255,255,255,0.3)", fontSize: 10, letterSpacing: "3px" }}>CURRENT OEE</div>
              <GaugeArc value={oeeVal} size={140} />
              <StatusBadge value={oeeVal} />
              <div style={{ color: "rgba(255,255,255,0.3)", fontSize: 10, textAlign: "center" }}>
                {latestWindow?.window_start
                  ? `Window: ${new Date(latestWindow.window_start).toLocaleTimeString()}`
                  : "No data yet"}
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gridTemplateRows: "1fr 1fr", gap: 12 }}>
              <StatCard label="Latest OEE"    value={oeeVal}   color="#00ff87" icon="◈" sub={`Machine: ${machine}`} />
              <StatCard label="24h Avg OEE"   value={avg24h}   color="#f59e0b" icon="∿" sub="Last 24 hours" />
              <StatCard label="24h Max OEE"   value={maxOEE}   color="#34d399" icon="↑" sub="Last 24 hours" />
              <StatCard label="24h Min OEE"   value={minOEE}   color="#ff6b6b" icon="↓" sub="Last 24 hours" />
              <StatCard label="Total Windows" value={totalWin} unit="" color="#60a5fa" icon="▦" sub="Last 24 hours" />
              <StatCard label="WS History"    value={history.length} unit="" color="#a78bfa" icon="≡" sub="Buffered windows" />
            </div>
          </div>

          {/* Row 2: Real-time OEE chart (raw events, no averaging) — full width */}
          <RealTimeOeeChart machine={machine} />

          {/* Row 3: Windowed OEE + ARIMA Forecast — full width */}
          <ForecastChart machine={machine} windowedHistory={history} />

          {/* Row 3.5: Predicted vs Actual OEE — full width */}
          <PredictedVsActualChart machine={machine} />

          {/* Row 4: APQ Breakdown (left 60%) | Shift Performance (right 40%) */}
          <div style={{ display: "grid", gridTemplateColumns: "60% 1fr", gap: 20 }}>
            <ApqChart machine={machine} />
            <ShiftChart machine={machine} />
          </div>

          {/* Row 5: SPC Control Chart — full width */}
          <SpcChart machine={machine} history={history} />

          {/* Row 6: 7 OEE Losses Pareto — full width */}
          <LossesChart machine={machine} />

          {/* Row 7: Window Aggregates table (left) | Alert Log (right) */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 20 }}>
            <WindowAggregatesTable machine={machine} history={history} />
            <AlertLog alerts={alerts} />
          </div>

        </div>
      )}
    </div>
  );
}

// ── Root: gate on auth ────────────────────────────────────────────────────────
export default function App() {
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token) { setAuthed(false); return; }
    fetch(`${API}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => { if (r.ok) setAuthed(true); else logout(); })
      .catch(() => setAuthed(!!getToken())); // offline — trust local token
  }, []);

  if (!authed) return <LoginScreen onLogin={() => setAuthed(true)} />;
  return <Dashboard />;
}
