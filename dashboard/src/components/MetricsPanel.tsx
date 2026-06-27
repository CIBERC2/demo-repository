import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Activity } from "lucide-react";

export type MetricPoint = {
  ts: string;
  cpu: number;
  mem: number;
};

type Props = {
  agentId: string | null;
  history: MetricPoint[];
  totalAgents: number;
  liveAgents: number;
};

function StatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color: string;
}) {
  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-3 flex flex-col gap-1">
      <span className="text-xs text-gray-600 uppercase tracking-widest">{label}</span>
      <span className={`text-2xl font-bold font-mono ${color}`}>{value}</span>
    </div>
  );
}

export function MetricsPanel({ agentId, history, totalAgents, liveAgents }: Props) {
  const latest = history[history.length - 1];

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3">
        <StatCard label="Total Agents" value={totalAgents} color="text-cyan-400 glow-accent" />
        <StatCard label="Live" value={liveAgents} color="text-green-400 glow-green" />
        <StatCard
          label="CPU %"
          value={latest ? `${latest.cpu.toFixed(1)}%` : "—"}
          color={
            (latest?.cpu ?? 0) > 80
              ? "text-red-400"
              : (latest?.cpu ?? 0) > 50
              ? "text-yellow-400"
              : "text-cyan-400"
          }
        />
        <StatCard
          label="MEM %"
          value={latest ? `${latest.mem.toFixed(1)}%` : "—"}
          color={
            (latest?.mem ?? 0) > 80
              ? "text-red-400"
              : (latest?.mem ?? 0) > 60
              ? "text-yellow-400"
              : "text-purple-400"
          }
        />
      </div>

      {/* Chart */}
      <div className="flex-1 bg-gray-900 rounded-lg border border-gray-800 p-3">
        <div className="flex items-center gap-2 mb-3">
          <Activity className="w-3.5 h-3.5 text-cyan-400" />
          <span className="text-xs text-gray-500">
            {agentId ? `Metrics — ${agentId.slice(0, 8)}` : "Select an agent"}
          </span>
        </div>
        {history.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-gray-700 text-xs">
            Waiting for heartbeats…
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={160}>
            <AreaChart data={history} margin={{ top: 4, right: 4, left: -24, bottom: 0 }}>
              <defs>
                <linearGradient id="cpu" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00d4ff" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#00d4ff" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="mem" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#a855f7" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#a855f7" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="ts" tick={{ fontSize: 9, fill: "#4b5563" }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 9, fill: "#4b5563" }} />
              <Tooltip
                contentStyle={{
                  background: "#111827",
                  border: "1px solid #1f2937",
                  borderRadius: "6px",
                  fontSize: "11px",
                  color: "#e2e8f0",
                }}
              />
              <Area
                type="monotone"
                dataKey="cpu"
                stroke="#00d4ff"
                strokeWidth={1.5}
                fill="url(#cpu)"
                dot={false}
                name="CPU %"
              />
              <Area
                type="monotone"
                dataKey="mem"
                stroke="#a855f7"
                strokeWidth={1.5}
                fill="url(#mem)"
                dot={false}
                name="MEM %"
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
