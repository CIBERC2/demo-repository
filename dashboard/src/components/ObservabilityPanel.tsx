import { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowLeftRight,
  CheckCircle,
  Clock,
  Terminal,
  Wifi,
  XCircle,
} from "lucide-react";

export interface ObsMetrics {
  commands_sent: number;
  results_received: number;
  agents_connected: number;
  agents_dead: number;
  channel_switches: number;
  avg_response_time_ms: number;
  errors: Array<{ ts: number; agent_id: string; error_type: string; detail: string }>;
  timeline: Array<{ ts: number; event: string; agent_id: string; detail: string }>;
}

interface Props {
  metrics: ObsMetrics | null;
}

const EVENT_STYLE: Record<string, { color: string; icon: React.ReactNode }> = {
  agent_online:    { color: "text-green-400",  icon: <Wifi       className="w-3 h-3" /> },
  agent_offline:   { color: "text-red-400",    icon: <XCircle    className="w-3 h-3" /> },
  command_sent:    { color: "text-cyan-400",   icon: <Terminal   className="w-3 h-3" /> },
  result_received: { color: "text-blue-400",   icon: <CheckCircle className="w-3 h-3" /> },
  result_error:    { color: "text-red-400",    icon: <XCircle    className="w-3 h-3" /> },
  channel_switch:  { color: "text-yellow-400", icon: <ArrowLeftRight className="w-3 h-3" /> },
  error:           { color: "text-red-500",    icon: <AlertTriangle  className="w-3 h-3" /> },
};

function KpiCard({
  label,
  value,
  icon,
  color = "text-cyan-400",
}: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  color?: string;
}) {
  return (
    <div className="bg-gray-900/80 border border-gray-700/60 rounded-lg p-3 flex flex-col gap-1">
      <div className={`flex items-center gap-1.5 text-xs text-gray-500`}>
        <span className={color}>{icon}</span>
        {label}
      </div>
      <div className={`text-xl font-bold font-mono ${color}`}>{value}</div>
    </div>
  );
}

export function ObservabilityPanel({ metrics }: Props) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  if (!metrics) {
    return (
      <div className="flex items-center justify-center h-32 text-gray-600 text-sm">
        <Activity className="w-4 h-4 mr-2 animate-pulse" />
        Esperando métricas…
      </div>
    );
  }

  const timeline = [...metrics.timeline].reverse();
  const errors   = [...metrics.errors].reverse();

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs text-gray-500 uppercase tracking-widest flex items-center gap-1.5">
        <Activity className="w-3 h-3 text-cyan-500" />
        Observabilidad
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-2">
        <KpiCard
          label="Agentes live"
          value={metrics.agents_connected}
          icon={<Wifi className="w-3.5 h-3.5" />}
          color={metrics.agents_connected > 0 ? "text-green-400" : "text-gray-600"}
        />
        <KpiCard
          label="Comandos"
          value={metrics.commands_sent}
          icon={<Terminal className="w-3.5 h-3.5" />}
          color="text-cyan-400"
        />
        <KpiCard
          label="Resp. prom."
          value={`${metrics.avg_response_time_ms.toFixed(0)}ms`}
          icon={<Clock className="w-3.5 h-3.5" />}
          color="text-purple-400"
        />
        <KpiCard
          label="Chan. switches"
          value={metrics.channel_switches}
          icon={<ArrowLeftRight className="w-3.5 h-3.5" />}
          color="text-yellow-400"
        />
      </div>

      {/* Errores recientes */}
      {errors.length > 0 && (
        <div className="bg-red-950/30 border border-red-800/40 rounded-lg p-2">
          <div className="text-xs text-red-400 font-bold mb-1.5 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" />
            Errores recientes
            <span className="ml-auto bg-red-800 text-red-200 text-[10px] rounded px-1.5 py-0.5">
              {errors.length}
            </span>
          </div>
          <div className="space-y-1">
            {errors.slice(0, 3).map((e, i) => (
              <div key={i} className="text-[10px] text-red-300 truncate">
                [{e.error_type}] {e.detail}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Timeline */}
      <div>
        <div className="text-[10px] text-gray-600 uppercase tracking-widest mb-1.5">
          Timeline ({timeline.length} eventos)
        </div>
        <div className="space-y-0.5 max-h-52 overflow-y-auto pr-1">
          {timeline.slice(0, 20).map((ev, i) => {
            const style = EVENT_STYLE[ev.event] ?? {
              color: "text-gray-400",
              icon: <Activity className="w-3 h-3" />,
            };
            const ts = new Date(ev.ts * 1000).toLocaleTimeString("en-US", { hour12: false });
            return (
              <div
                key={i}
                className="flex items-center gap-1.5 text-[10px] py-0.5 border-b border-gray-800/40"
              >
                <span className="text-gray-600 shrink-0 w-14">{ts}</span>
                <span className={`${style.color} shrink-0`}>{style.icon}</span>
                <span className={`${style.color} shrink-0 font-mono`}>{ev.event}</span>
                <span className="text-gray-500 truncate">{ev.agent_id.slice(0, 8)} {ev.detail}</span>
              </div>
            );
          })}
          {timeline.length === 0 && (
            <div className="text-gray-700 text-[10px] text-center py-4">Sin eventos aún</div>
          )}
        </div>
      </div>
    </div>
  );
}
