import { useState, useEffect, useCallback } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, AreaChart, Area,
  BarChart, Bar, ComposedChart, Legend, Cell,
} from "recharts";
import { login, logout, register, getToken, authHeader } from "./api/auth";
import { useOeeWebSocket } from "./hooks/useOeeWebSocket";
import { useAlertsWebSocket } from "./hooks/useAlertsWebSocket";

const API = "http://localhost:8000";

function getThreshold(value) {
  if (value >= 85) return { label: "WORLD CLASS", color: "#00ff87", bg: "rgba(0,255,135,0.1)" };
  if (value >= 75) return { label: "GOOD",        color: "#f5c518", bg: "rgba(245,197,24,0.1)" };
  if (value >= 60) return { label: "AVERAGE",     color: "#ff8c42", bg: "rgba(255,140,66,0.1)" };
  return              { label: "POOR",             color: "#ff4757", bg: "rgba(255,71,87,0.1)" };
}

// ── Login Screen ──────────────────────────────────────────────────────────────
function LoginScreen({ onLogin }) {
  const [mode, setMode]         = useState("login"); // "login" | "signup"
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
          <input
            type="text" placeholder="Username" value={username}
            onChange={(e) => setUsername(e.target.value)} required
            style={inputStyle}
          />
          <input
            type="password" placeholder="Password" value={password}
            onChange={(e) => setPassword(e.target.value)} required
            style={inputStyle}
          />
          {mode === "signup" && (
            <input
              type="password" placeholder="Confirm Password" value={confirm}
              onChange={(e) => setConfirm(e.target.value)} required
              style={inputStyle}
            />
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

const inputStyle = {
  background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)",
  borderRadius: 8, padding: "10px 14px", color: "#e8eaf0", fontFamily: "'Inter', sans-serif",
  fontSize: 14, outline: "none", width: "100%", boxSizing: "border-box",
};

// ── Sub-components ────────────────────────────────────────────────────────────
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

function StatusBadge({ value }) {
  const t = getThreshold(value);
  return (
    <span style={{ background: t.bg, border: `1px solid ${t.color}`, color: t.color,
      padding: "2px 10px", borderRadius: 4, fontSize: 11, fontFamily: "'Inter', sans-serif",
      letterSpacing: "1px", fontWeight: 700 }}>{t.label}</span>
  );
}

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

// ── APQ Breakdown Chart ───────────────────────────────────────────────────────
function ApqChart({ machine }) {
  const [apqData, setApqData] = useState([]);
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
      borderRadius: 16, padding: "20px 24px" }}>
      <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: "2px", color: "rgba(255,255,255,0.8)", marginBottom: 16 }}>
        APQ BREAKDOWN
      </div>
      {apqError ? (
        <div style={{ color: "#ff4757", fontSize: 12 }}>{apqError}</div>
      ) : formatted.length === 0 ? (
        <div style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center",
          color: "rgba(255,255,255,0.2)", fontSize: 12 }}>No APQ data available</div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={formatted} margin={{ top: 10, right: 20, bottom: 30, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey="time"
              tick={{ fill: "rgba(255,255,255,0.55)", fontSize: 11 }}
              tickLine={false} axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
              interval={Math.max(0, Math.floor(formatted.length / 6) - 1)}
              label={{ value: "Time (window start)", position: "insideBottom", offset: -18, fill: "rgba(255,255,255,0.45)", fontSize: 11 }} />
            <YAxis
              domain={([dataMin, dataMax]) => {
                const pad = Math.max((dataMax - dataMin) * 0.2, 5);
                return [Math.max(0, Math.floor(dataMin - pad)), Math.min(100, Math.ceil(dataMax + pad))];
              }}
              tick={{ fill: "rgba(255,255,255,0.55)", fontSize: 11 }}
              tickLine={false} axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
              tickFormatter={(v) => `${v}%`} width={44}
              label={{ value: "Component (%)", angle: -90, position: "insideLeft", offset: 12, fill: "rgba(255,255,255,0.45)", fontSize: 11 }} />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ fontSize: 12, color: "rgba(255,255,255,0.65)" }} />
            <ReferenceLine y={85} stroke="rgba(0,255,135,0.5)" strokeDasharray="4 4"
              label={{ value: "85% World Class", fill: "rgba(0,255,135,0.8)", fontSize: 12, fontWeight: 600 }} />
            <Bar dataKey="avg_availability" name="Availability" fill="#60a5fa" />
            <Bar dataKey="avg_performance"  name="Performance"  fill="#f59e0b" />
            <Bar dataKey="avg_quality"      name="Quality"      fill="#34d399" />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// ── SPC Control Chart ─────────────────────────────────────────────────────────
function SpcChart({ machine, history }) {
  const [spc, setSpc] = useState(null);

  useEffect(() => {
    if (!machine) return;
    fetch(`${API}/api/spc?machine=${machine}`, { headers: authHeader() })
      .then((r) => r.json())
      .then((data) => setSpc(data.length > 0 ? data[0] : null))
      .catch(() => setSpc(null));
  }, [machine]);

  // Build Y domain that always includes UCL and LCL so reference lines are visible
  const spcDomain = ([dataMin, dataMax]) => {
    const allVals = [dataMin, dataMax];
    if (spc) { allVals.push(spc.ucl, spc.lcl, spc.mean_value); }
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
          <div style={{ fontSize: 14, fontWeight: 700, letterSpacing: "2px", color: "#e8eaf0" }}>SPC CONTROL CHART</div>
          <div style={{ fontSize: 11, color: "rgba(255,255,255,0.4)", marginTop: 4 }}>
            Statistical Process Control — OEE vs control limits
          </div>
        </div>
        {/* Legend pills */}
        {spc && (
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
            {[
              { label: `UCL  ${spc.ucl.toFixed(1)}%`,        color: "#ff4757", bg: "rgba(255,71,87,0.12)" },
              { label: `Mean ${spc.mean_value.toFixed(1)}%`,  color: "#f59e0b", bg: "rgba(245,158,11,0.12)" },
              { label: `LCL  ${spc.lcl.toFixed(1)}%`,         color: "#ff4757", bg: "rgba(255,71,87,0.12)" },
            ].map(({ label, color, bg }) => (
              <span key={label} style={{
                background: bg, border: `1px solid ${color}60`,
                color, padding: "3px 10px", borderRadius: 6,
                fontSize: 11, fontFamily: "monospace", fontWeight: 700,
                letterSpacing: "0.5px", whiteSpace: "nowrap",
              }}>{label}</span>
            ))}
          </div>
        )}
        {!spc && <span style={{ fontSize: 11, color: "rgba(255,255,255,0.3)" }}>SPC data pending (needs ≥10 windows)</span>}
      </div>

      {history.length === 0 ? (
        <div style={{ height: 260, display: "flex", alignItems: "center", justifyContent: "center",
          color: "rgba(255,255,255,0.2)", fontSize: 13 }}>No OEE history yet</div>
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={history} margin={{ top: 10, right: 60, bottom: 30, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
            <XAxis
              dataKey="time"
              tick={{ fill: "rgba(255,255,255,0.5)", fontSize: 11 }}
              tickLine={false} axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
              interval={Math.max(0, Math.floor(history.length / 6) - 1)}
              label={{ value: "Time (window start)", position: "insideBottom", offset: -18,
                fill: "rgba(255,255,255,0.4)", fontSize: 11 }} />
            <YAxis
              domain={spcDomain}
              tick={{ fill: "rgba(255,255,255,0.5)", fontSize: 11 }}
              tickLine={false} axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
              tickFormatter={(v) => `${v}%`}
              width={60}
              label={{ value: "OEE (%)", angle: -90, position: "insideLeft", offset: 12,
                fill: "rgba(255,255,255,0.4)", fontSize: 11 }} />
            <Tooltip content={<CustomTooltip />} />

            {/* UCL line */}
            {spc && (
              <ReferenceLine y={spc.ucl} stroke="#ff4757" strokeWidth={1.5} strokeDasharray="6 3"
                label={{ value: `UCL ${spc.ucl.toFixed(1)}%`, position: "right",
                  fill: "#ff4757", fontSize: 12, fontWeight: 700 }} />
            )}
            {/* Mean line */}
            {spc && (
              <ReferenceLine y={spc.mean_value} stroke="#f59e0b" strokeWidth={1.5} strokeDasharray="8 3"
                label={{ value: `Mean ${spc.mean_value.toFixed(1)}%`, position: "right",
                  fill: "#f59e0b", fontSize: 12, fontWeight: 700 }} />
            )}
            {/* LCL line */}
            {spc && (
              <ReferenceLine y={spc.lcl} stroke="#ff4757" strokeWidth={1.5} strokeDasharray="6 3"
                label={{ value: `LCL ${spc.lcl.toFixed(1)}%`, position: "right",
                  fill: "#ff4757", fontSize: 12, fontWeight: 700 }} />
            )}

            <Line type="monotone" dataKey="oee" name="OEE" stroke="#00ff87" strokeWidth={2.5}
              isAnimationActive={false}
              dot={(props) => {
                const { cx, cy, value } = props;
                const outOfControl = spc && (value > spc.ucl || value < spc.lcl);
                return (
                  <circle key={`dot-${cx}-${cy}`} cx={cx} cy={cy} r={outOfControl ? 5 : 3.5}
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

// ── Six Big Losses Pareto Chart ───────────────────────────────────────────────
const SIX_BIG_LOSSES_INFO = {
  "Equipment Failure": {
    icon: "🔧",
    color: "#ff4757",
    desc: "Unplanned breakdowns — machine stops completely. Hits Availability.",
    example: "Vacuum leak, chamber failure, PM overrun",
  },
  "Reduced Speed": {
    icon: "🐢",
    color: "#f59e0b",
    desc: "Machine runs slower than design rate. Hits Performance.",
    example: "Pad wear, vibration, recipe throttling",
  },
  "Process Defects": {
    icon: "⚠",
    color: "#60a5fa",
    desc: "Wafers scrapped or reworked during steady-state production. Hits Quality.",
    example: "Particle contamination, slurry imbalance, reticle haze",
  },
};

function LossesChart({ machine }) {
  const [lossData, setLossData] = useState([]);
  const [hoveredLoss, setHoveredLoss] = useState(null);

  useEffect(() => {
    if (!machine) return;
    fetch(`${API}/api/losses?machine=${machine}`, { headers: authHeader() })
      .then((r) => r.json())
      .then((data) => {
        const sorted = [...data].sort((a, b) => b.total_loss_percentage - a.total_loss_percentage);
        let cumulative = 0;
        const total = sorted.reduce((s, d) => s + Number(d.total_loss_percentage), 0);
        const withCumulative = sorted.map((d) => {
          cumulative += Number(d.total_loss_percentage);
          return { ...d, cumulative_pct: total > 0 ? parseFloat((cumulative / total * 100).toFixed(1)) : 0 };
        });
        setLossData(withCumulative);
      })
      .catch(() => setLossData([]));
  }, [machine]);

  const barColors = lossData.map((d) => SIX_BIG_LOSSES_INFO[d.loss_type]?.color || "#f59e0b");

  return (
    <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 16, padding: "20px 24px" }}>
      {/* Header */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: "2px", color: "rgba(255,255,255,0.8)" }}>
          SIX BIG LOSSES
        </div>
        <div style={{ fontSize: 10, color: "rgba(255,255,255,0.35)", marginTop: 3 }}>
          Pareto chart — bars show loss magnitude, red line shows cumulative %. Fix the tallest bars first (80/20 rule).
        </div>
      </div>

      {/* Legend / explanation pills */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
        {Object.entries(SIX_BIG_LOSSES_INFO).map(([name, info]) => (
          <div key={name}
            onMouseEnter={() => setHoveredLoss(name)}
            onMouseLeave={() => setHoveredLoss(null)}
            style={{ background: `${info.color}15`, border: `1px solid ${info.color}40`,
              borderRadius: 6, padding: "4px 10px", cursor: "default",
              transition: "border-color 0.15s",
              borderColor: hoveredLoss === name ? info.color : `${info.color}40` }}>
            <span style={{ fontSize: 10, color: info.color, fontWeight: 700 }}>{info.icon} {name}</span>
          </div>
        ))}
      </div>

      {/* Hover explanation */}
      {hoveredLoss && SIX_BIG_LOSSES_INFO[hoveredLoss] && (
        <div style={{ background: "rgba(255,255,255,0.04)", border: `1px solid ${SIX_BIG_LOSSES_INFO[hoveredLoss].color}30`,
          borderRadius: 8, padding: "8px 12px", marginBottom: 12, fontSize: 11 }}>
          <div style={{ color: SIX_BIG_LOSSES_INFO[hoveredLoss].color, fontWeight: 700, marginBottom: 2 }}>
            {SIX_BIG_LOSSES_INFO[hoveredLoss].icon} {hoveredLoss}
          </div>
          <div style={{ color: "rgba(255,255,255,0.6)", lineHeight: 1.5 }}>
            {SIX_BIG_LOSSES_INFO[hoveredLoss].desc}
          </div>
          <div style={{ color: "rgba(255,255,255,0.3)", marginTop: 3 }}>
            Examples: {SIX_BIG_LOSSES_INFO[hoveredLoss].example}
          </div>
        </div>
      )}

      {lossData.length === 0 ? (
        <div style={{ height: 180, display: "flex", alignItems: "center", justifyContent: "center",
          color: "rgba(255,255,255,0.2)", fontSize: 12 }}>No loss data available</div>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <ComposedChart data={lossData} margin={{ top: 5, right: 50, bottom: 40, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey="loss_type"
              tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 10 }}
              tickLine={false} axisLine={false}
              label={{ value: "Loss Category", position: "insideBottom", offset: -28,
                fill: "rgba(255,255,255,0.3)", fontSize: 10 }} />
            <YAxis yAxisId="left"
              tick={{ fill: "rgba(255,255,255,0.35)", fontSize: 10 }} tickLine={false} axisLine={false}
              tickFormatter={(v) => `${v}%`} width={44}
              label={{ value: "Loss (%)", angle: -90, position: "insideLeft", offset: 12,
                fill: "rgba(255,255,255,0.3)", fontSize: 10 }} />
            <YAxis yAxisId="right" orientation="right" domain={[0, 100]}
              tick={{ fill: "rgba(255,255,255,0.35)", fontSize: 10 }} tickLine={false} axisLine={false}
              tickFormatter={(v) => `${v}%`}
              label={{ value: "Cumulative (%)", angle: 90, position: "insideRight", offset: 10,
                fill: "rgba(255,255,255,0.3)", fontSize: 10 }} />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0]?.payload;
                const info = SIX_BIG_LOSSES_INFO[d?.loss_type];
                return (
                  <div style={{ background: "#0d1117", border: "1px solid rgba(255,255,255,0.15)",
                    borderRadius: 8, padding: "10px 14px", fontFamily: "monospace", maxWidth: 220 }}>
                    <div style={{ color: info?.color || "#f59e0b", fontWeight: 700, fontSize: 11, marginBottom: 4 }}>
                      {info?.icon} {d?.loss_type}
                    </div>
                    <div style={{ color: "rgba(255,255,255,0.7)", fontSize: 11 }}>
                      Loss: <strong>{Number(d?.total_loss_percentage).toFixed(2)}%</strong>
                    </div>
                    <div style={{ color: "rgba(255,255,255,0.5)", fontSize: 11 }}>
                      Cumulative: <strong>{d?.cumulative_pct}%</strong>
                    </div>
                    {info && (
                      <div style={{ color: "rgba(255,255,255,0.35)", fontSize: 10, marginTop: 6, lineHeight: 1.4 }}>
                        {info.desc}
                      </div>
                    )}
                  </div>
                );
              }}
            />
            <Bar yAxisId="left" dataKey="total_loss_percentage" name="Loss %"
              label={{ position: "top", fill: "rgba(255,255,255,0.5)", fontSize: 10,
                formatter: (v) => `${Number(v).toFixed(1)}%` }}>
              {lossData.map((entry, index) => (
                <Cell key={`cell-${index}`}
                  fill={SIX_BIG_LOSSES_INFO[entry.loss_type]?.color || "#f59e0b"} />
              ))}
            </Bar>
            <Line yAxisId="right" type="monotone" dataKey="cumulative_pct" name="Cumulative %"
              stroke="#ff4757" strokeWidth={2} dot={{ r: 3, fill: "#ff4757" }} />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// ── Fleet View: all machines raw OEE charts simultaneously ───────────────────
const MACHINE_COLORS = {
  "LITHO_ASML_01":  "#00ff87",
  "ETCH_LAM_02":    "#60a5fa",
  "DEP_AMAT_03":    "#f59e0b",
  "CMP_EBARA_04":   "#a78bfa",
  "INSPECT_KLA_05": "#34d399",
};

function FleetView({ machines }) {
  const [restRawByMachine, setRestRawByMachine] = useState({});

  useEffect(() => {
    if (!machines.length) return;
    const fetchAll = () => {
      Promise.all(
        machines.map((m) =>
          fetch(`${API}/api/oee/raw?machine=${m}&limit=15`, { headers: authHeader() })
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
        ALL MACHINES · LIVE RAW OEE · LAST 15 EVENTS PER MACHINE
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        {machines.map((machineId) => {
          const color = MACHINE_COLORS[machineId] || "#00ff87";
          const history = (restRawByMachine[machineId] || [])
            .sort((a, b) => new Date(a.event_time) - new Date(b.event_time))
            .slice(-15)
            .map((r) => ({
              time: new Date(r.event_time).toLocaleTimeString(),
              oee: parseFloat(Number(r.oee).toFixed(2)),
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
                    {history.length} RAW EVENTS (LAST 15)
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
                <div style={{ height: 160, display: "flex", alignItems: "center", justifyContent: "center",
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
                      tickFormatter={(v) => `${v}%`}
                      width={36} />
                    <Tooltip content={<CustomTooltip />} />
                    <ReferenceLine y={85} stroke="rgba(255,255,255,0.1)" strokeDasharray="4 4" />
                    <Area type="monotone" dataKey="oee" name="OEE"
                      stroke={color} strokeWidth={1.5}
                      fill={`url(#grad-${machineId})`}
                      dot={false}
                      activeDot={{ r: 3, fill: color }}
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
  const { alerts } = useAlertsWebSocket();
  const [restRawData, setRestRawData] = useState([]);

  // REST poll for raw events — sole source of truth, no WS switching
  useEffect(() => {
    if (!machine) return;
    const poll = () => {
      fetch(`${API}/api/oee/raw?machine=${machine}&limit=15`, { headers: authHeader() })
        .then((r) => r.ok ? r.json() : [])
        .then((data) => setRestRawData(Array.isArray(data) ? data : []))
        .catch(() => {});
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, [machine]);

  const effectiveRawHistory = restRawData
    .sort((a, b) => new Date(a.event_time) - new Date(b.event_time))
    .slice(-15)
    .map((r) => ({
      time: new Date(r.event_time).toLocaleTimeString(),
      oee: parseFloat(Number(r.oee).toFixed(2)),
      event_time: r.event_time,
      loss: r.loss_event_name || null,
    }));

  // Windowed history still used for SPC chart (needs avg_oee windows)
  const history = oeeData
    .filter((r) => r.machine_id === machine)
    .sort((a, b) => new Date(a.window_start) - new Date(b.window_start))
    .map((r) => ({
      time: new Date(r.window_start).toLocaleTimeString(),
      oee: parseFloat(Number(r.avg_oee).toFixed(2)),
      window_start: r.window_start,
      window_end: r.window_end,
    }));
  const latest = effectiveRawHistory.length > 0 ? effectiveRawHistory[effectiveRawHistory.length - 1] : history.length > 0 ? history[history.length - 1] : null;

  // fetch machine list once
  useEffect(() => {
    fetch(`${API}/api/machines`, { headers: authHeader() })
      .then((r) => {
        if (r.status === 401) { logout(); return []; }
        return r.json();
      })
      .then((list) => {
        setMachines(list);
        if (list.length > 0) setMachine(list[0]);
        else setLoading(false); // no machines — stop spinner
      })
      .catch(() => { setError("Cannot reach API on port 8000"); setLoading(false); });
  }, []);

  // Fetch stats separately (still REST)
  useEffect(() => {
    if (!machine) return;
    setError(null);
    fetch(`${API}/api/oee/stats?machine=${machine}`, { headers: authHeader() })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((st) => { setStats(st); setLastRefresh(new Date().toLocaleTimeString()); setLoading(false); })
      .catch(() => { setLoading(false); }); // don't block on stats failure
  }, [machine]);

  const current = latest ? { avg_oee: latest.oee, event_time: latest.event_time } : {};
  const oeeVal  = Number(latest?.oee || 0);
  const avg15   = Number(stats?.avg_oee  || 0);
  const minOEE  = Number(stats?.min_oee  || 0);
  const maxOEE  = Number(stats?.max_oee  || 0);
  const thresh  = getThreshold(oeeVal);

  return (
    <div style={{ minHeight: "100vh", background: "#080b10", color: "#e8eaf0",
      fontFamily: "'Inter', system-ui, sans-serif", padding: 0 }}>
      <style>{`
        @keyframes pulse   { 0%,100%{opacity:1}50%{opacity:0.3} }
        @keyframes slideIn { from{transform:translateX(20px);opacity:0}to{transform:translateX(0);opacity:1} }
        @keyframes spin    { from{transform:rotate(0deg)}to{transform:rotate(360deg)} }
      `}</style>

      {/* Top Bar */}
      <div style={{ background: "rgba(8,11,16,0.97)", borderBottom: "1px solid rgba(0,255,135,0.15)",
        padding: "12px 32px", display: "flex", alignItems: "center", justifyContent: "space-between",
        position: "sticky", top: 0, zIndex: 100 }}>
        <div>
          <div style={{ color: "#00ff87", fontSize: 18, fontWeight: 800, letterSpacing: "3px" }}>⬡ OEE MONITOR</div>
          <div style={{ color: "rgba(255,255,255,0.3)", fontSize: 10, letterSpacing: "2px" }}>KAFKA → SPARK → POSTGRES → REACT</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>

          {/* View toggle nav buttons */}
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

          {lastRefresh && <span style={{ color: "rgba(255,255,255,0.3)", fontSize: 10 }}>Last: {lastRefresh}</span>}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 7, height: 7, borderRadius: "50%", background: error ? "#ff4757" : "#00ff87",
              boxShadow: `0 0 8px ${error ? "#ff4757" : "#00ff87"}`, animation: "pulse 1.5s infinite" }} />
            <span style={{ color: "rgba(255,255,255,0.5)", fontSize: 11, letterSpacing: "1px" }}>
              {error ? "DISCONNECTED" : wsConnected ? "LIVE · WS" : "RECONNECTING"}
            </span>
          </div>

          {/* Machine selector — only shown in machine view */}
          {view === "machine" && (
            <select value={machine} onChange={(e) => setMachine(e.target.value)}
              style={{ background: "rgba(0,255,135,0.08)", border: "1px solid rgba(0,255,135,0.3)",
                color: "#00ff87", padding: "6px 12px", borderRadius: 6, fontFamily: "monospace",
                fontSize: 12, cursor: "pointer", outline: "none" }}>
              {machines.map((m) => <option key={m} value={m} style={{ background: "#0d1117" }}>{m}</option>)}
            </select>
          )}

          <button onClick={logout}
            style={{ background: "transparent", border: "1px solid rgba(255,71,87,0.3)", color: "#ff4757",
              padding: "5px 12px", borderRadius: 6, fontFamily: "monospace", fontSize: 10,
              letterSpacing: "1px", cursor: "pointer" }}>LOGOUT</button>
        </div>
      </div>

      {error && (
        <div style={{ background: "rgba(255,71,87,0.1)", border: "1px solid rgba(255,71,87,0.4)",
          margin: "16px 32px", padding: "12px 20px", borderRadius: 8, color: "#ff4757", fontSize: 12 }}>
          ⚠ {error}
        </div>
      )}

      {loading && !error && (
        <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 200 }}>
          <div style={{ width: 32, height: 32, border: "3px solid rgba(0,255,135,0.1)",
            borderTop: "3px solid #00ff87", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
        </div>
      )}

      {/* Fleet View */}
      {!loading && view === "fleet" && (
        <FleetView machines={machines} />
      )}

      {/* Machine View */}
      {!loading && view === "machine" && (
        <div style={{ padding: "24px 32px", display: "flex", flexDirection: "column", gap: 24 }}>

          {/* Row 1: Gauge + KPIs */}
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
                {current.event_time
                  ? `Last event: ${new Date(current.event_time).toLocaleTimeString()}`
                  : "No data yet"}
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gridTemplateRows: "1fr 1fr", gap: 12 }}>
              <StatCard label="Latest OEE"    value={oeeVal}  color="#00ff87" icon="◈" sub={`Machine: ${machine}`} />
              <StatCard label="15-min Avg"    value={avg15}   color="#f59e0b" icon="∿" sub="Last 15 minutes" />
              <StatCard label="15-min Max"    value={maxOEE}  color="#34d399" icon="↑" sub="Rolling window" />
              <StatCard label="15-min Min"    value={minOEE}  color="#ff6b6b" icon="↓" sub="Rolling window" />
              <StatCard label="Total Windows" value={stats?.total_windows || 0} unit="" color="#60a5fa" icon="▦" sub="In last 15 min" />
              <StatCard label="Raw Events"    value={effectiveRawHistory.length} unit="" color="#a78bfa" icon="≡" sub="Last 30 min" />
            </div>
          </div>

          {/* Row 2: OEE Trend — raw per-event data only */}
          <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
            borderRadius: 16, padding: "20px 24px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: "2px", color: "rgba(255,255,255,0.8)" }}>OEE TREND</div>
                <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", marginTop: 2 }}>
                  Raw per-event OEE · last 15 readings from the machine
                </div>
              </div>
              <span style={{ fontSize: 10, color: "rgba(255,255,255,0.25)" }}>{effectiveRawHistory.length} EVENTS</span>
            </div>
            {effectiveRawHistory.length === 0 ? (
              <div style={{ height: 180, display: "flex", alignItems: "center", justifyContent: "center",
                color: "rgba(255,255,255,0.2)", fontSize: 12 }}>
                No raw events yet — producer and Spark job need to be running
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={effectiveRawHistory} margin={{ top: 10, right: 60, bottom: 30, left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="time"
                    tick={{ fill: "rgba(255,255,255,0.55)", fontSize: 11 }}
                    tickLine={false} axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
                    interval={0}
                    label={{ value: "Event time", position: "insideBottom", offset: -18, fill: "rgba(255,255,255,0.45)", fontSize: 11 }} />
                  <YAxis
                    domain={([dataMin, dataMax]) => {
                      const pad = Math.max((dataMax - dataMin) * 0.3, 3);
                      return [Math.max(0, Math.floor(dataMin - pad)), Math.min(100, Math.ceil(dataMax + pad))];
                    }}
                    tick={{ fill: "rgba(255,255,255,0.55)", fontSize: 11 }}
                    tickLine={false} axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
                    tickFormatter={(v) => `${v}%`} width={60}
                    label={{ value: "OEE (%)", angle: -90, position: "insideLeft", offset: 12, fill: "rgba(255,255,255,0.45)", fontSize: 11 }} />
                  <Tooltip
                    content={({ active, payload, label }) => {
                      if (!active || !payload?.length) return null;
                      const d = payload[0]?.payload;
                      return (
                        <div style={{ background: "#0d1117", border: "1px solid rgba(0,255,135,0.3)",
                          borderRadius: 8, padding: "10px 14px", fontFamily: "monospace" }}>
                          <div style={{ color: "rgba(255,255,255,0.5)", fontSize: 11, marginBottom: 4 }}>{label}</div>
                          <div style={{ color: "#00ff87", fontSize: 12 }}>
                            OEE: <strong>{Number(d?.oee).toFixed(2)}%</strong>
                          </div>
                          {d?.loss && (
                            <div style={{ color: "#f59e0b", fontSize: 11, marginTop: 3 }}>⚠ Loss: {d.loss}</div>
                          )}
                        </div>
                      );
                    }}
                  />
                  <ReferenceLine y={85} stroke="rgba(0,255,135,0.5)" strokeDasharray="4 4"
                    label={{ value: "85%", position: "right", fill: "rgba(0,255,135,0.85)", fontSize: 11 }} />
                  <ReferenceLine y={75} stroke="rgba(245,197,24,0.5)" strokeDasharray="4 4"
                    label={{ value: "75%", position: "right", fill: "rgba(245,197,24,0.85)", fontSize: 11 }} />
                  <Line type="monotone" dataKey="oee" name="OEE" stroke="#00ff87" strokeWidth={1.5}
                    dot={(props) => {
                      const { cx, cy, payload } = props;
                      if (payload.loss) {
                        return <circle key={`dot-${cx}-${cy}`} cx={cx} cy={cy} r={4}
                          fill="#f59e0b" stroke="rgba(245,158,11,0.4)" strokeWidth={3} />;
                      }
                      return <circle key={`dot-${cx}-${cy}`} cx={cx} cy={cy} r={3}
                        fill="#00ff87" strokeWidth={0} />;
                    }}
                    activeDot={{ r: 5, fill: "#00ff87" }}
                    isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Row 3: Table + Alerts */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 20 }}>
            <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
              borderRadius: 16, overflow: "hidden" }}>
              <div style={{ padding: "16px 24px", borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
                <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: "2px", color: "rgba(255,255,255,0.8)" }}>
                  WINDOW AGGREGATES
                </div>
                <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", marginTop: 2 }}>
                  Live from oee_data · Spark micro-batches
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
                  </tbody>
                </table>
              </div>
            </div>

            <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
              borderRadius: 16, overflow: "hidden", display: "flex", flexDirection: "column" }}>
              <div style={{ padding: "16px 20px", borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
                <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: "2px", color: "rgba(255,255,255,0.8)" }}>ALERT LOG</div>
                <div style={{ fontSize: 10, color: "rgba(255,255,255,0.3)", marginTop: 2 }}>
                  WARNING ≥ OEE &lt; 60% · CRITICAL &lt; 45% · ANOMALY = statistical outlier
                </div>
              </div>
              <div style={{ flex: 1, padding: "12px 16px", display: "flex", flexDirection: "column",
                gap: 8, overflowY: "auto", maxHeight: 280 }}>
                {alerts.length === 0 ? (
                  <div style={{ color: "rgba(255,255,255,0.2)", fontSize: 11, textAlign: "center", marginTop: 30 }}>
                    ✓ No alerts — system nominal
                  </div>
                ) : [...alerts].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 10).map((a) => {
                  const isCrit = a.alert_level === "CRITICAL" || a.alert_level === "ANOMALY";
                  const explanations = {
                    WARNING:  "OEE dropped below 60% — monitor closely for further degradation.",
                    CRITICAL: "OEE below 45% — immediate intervention required to restore production.",
                    ANOMALY:  "OEE is a statistical outlier (>2σ below rolling mean) — unexpected process deviation detected.",
                  };
                  const explanation = explanations[a.alert_level] || "Unexpected alert condition.";
                  return (
                    <div key={a.id} style={{
                      background: isCrit ? "rgba(255,71,87,0.08)" : "rgba(255,140,66,0.08)",
                      border: `1px solid ${isCrit ? "rgba(255,71,87,0.3)" : "rgba(255,140,66,0.3)"}`,
                      borderRadius: 8, padding: "8px 12px", animation: "slideIn 0.3s ease" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div style={{ fontSize: 10, color: isCrit ? "#ff4757" : "#ff8c42", fontWeight: 700 }}>
                          {a.alert_level === "ANOMALY" ? "⚡ ANOMALY" : isCrit ? "⚠ CRITICAL" : "△ WARNING"} · {a.machine_id}
                        </div>
                        <div style={{ fontSize: 9, color: "rgba(255,255,255,0.2)" }}>
                          {a.created_at ? new Date(a.created_at).toLocaleTimeString() : ""}
                        </div>
                      </div>
                      <div style={{ fontSize: 11, color: "rgba(255,255,255,0.7)", marginTop: 3 }}>
                        OEE: <strong>{Number(a.avg_oee).toFixed(2)}%</strong>
                        {a.threshold != null && <span style={{ color: "rgba(255,255,255,0.35)" }}> · threshold: {Number(a.threshold).toFixed(1)}%</span>}
                      </div>
                      <div style={{ fontSize: 10, color: "rgba(255,255,255,0.35)", marginTop: 3, lineHeight: 1.4 }}>
                        {explanation}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Row 4: APQ Breakdown */}
          <ApqChart machine={machine} />

          {/* Row 5: SPC Control Chart */}
          <SpcChart machine={machine} history={history} />

          {/* Row 6: Six Big Losses — full width */}
          <LossesChart machine={machine} />

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
    // Validate token is still accepted by the API
    fetch(`${API}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => { if (r.ok) setAuthed(true); else { logout(); } })
      .catch(() => setAuthed(!!getToken())); // offline — trust local token
  }, []);

  if (!authed) return <LoginScreen onLogin={() => setAuthed(true)} />;
  return <Dashboard />;
}
