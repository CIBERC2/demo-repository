import { Cpu, HardDrive, Wifi, WifiOff } from "lucide-react";

export type Agent = {
  agent_id: string;
  hostname: string;
  label?: string;
  os: string;
  arch: string;
  user: string;
  capabilities: string[];
  plugins: string[];
  first_seen: number;
  last_seen: number;
  connected: boolean;
  metrics: { cpu?: number; mem?: number; uptime?: number };
};

type Props = {
  agents: Agent[];
  selected: string | null;
  onSelect: (id: string) => void;
};

function timeAgo(ts: number) {
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

export function AgentList({ agents, selected, onSelect }: Props) {
  if (agents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-48 text-gray-600">
        <WifiOff className="w-8 h-8 mb-2" />
        <span className="text-sm">No agents connected</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {agents.map((a) => {
        const isSelected = a.agent_id === selected;
        const cpu = a.metrics?.cpu ?? 0;
        const mem = a.metrics?.mem ?? 0;
        const shortId = a.agent_id.slice(0, 8);

        return (
          <button
            key={a.agent_id}
            onClick={() => onSelect(a.agent_id)}
            className={`w-full text-left rounded-lg border p-3 transition-all duration-150 ${
              isSelected
                ? "border-cyan-400 bg-cyan-400/5"
                : "border-gray-800 hover:border-gray-600 bg-gray-900/50"
            }`}
          >
            {/* header row */}
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                {a.connected ? (
                  <Wifi className="w-3.5 h-3.5 text-green-400" />
                ) : (
                  <WifiOff className="w-3.5 h-3.5 text-red-500" />
                )}
                <span
                  className={`text-sm font-bold ${
                    isSelected ? "text-cyan-400 glow-accent" : "text-gray-200"
                  }`}
                >
                  {a.hostname}
                </span>
                {a.label && (
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-purple-900/50 text-purple-300 border border-purple-700">
                    {a.label}
                  </span>
                )}
              </div>
              <span className="text-xs text-gray-600 font-mono">{shortId}</span>
            </div>

            {/* meta row */}
            <div className="flex items-center gap-3 text-xs text-gray-500 mb-2">
              <span>{a.os} / {a.arch}</span>
              <span className="text-gray-700">·</span>
              <span>{a.user}</span>
              <span className="text-gray-700">·</span>
              <span>{timeAgo(a.last_seen)}</span>
            </div>

            {/* metrics */}
            {a.connected && (
              <div className="flex gap-4 text-xs">
                <div className="flex items-center gap-1">
                  <Cpu className="w-3 h-3 text-cyan-600" />
                  <div className="flex items-center gap-1">
                    <div className="w-16 h-1 bg-gray-800 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${
                          cpu > 80 ? "bg-red-500" : cpu > 50 ? "bg-yellow-500" : "bg-cyan-500"
                        }`}
                        style={{ width: `${cpu}%` }}
                      />
                    </div>
                    <span className="text-gray-400">{cpu.toFixed(1)}%</span>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <HardDrive className="w-3 h-3 text-purple-600" />
                  <div className="flex items-center gap-1">
                    <div className="w-16 h-1 bg-gray-800 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${
                          mem > 80 ? "bg-red-500" : mem > 60 ? "bg-yellow-500" : "bg-purple-500"
                        }`}
                        style={{ width: `${mem}%` }}
                      />
                    </div>
                    <span className="text-gray-400">{mem.toFixed(1)}%</span>
                  </div>
                </div>
              </div>
            )}

            {/* plugins */}
            {(a.plugins?.length > 0 || a.capabilities?.length > 0) && (
              <div className="flex flex-wrap gap-1 mt-2">
                {(a.plugins?.length > 0 ? a.plugins : a.capabilities).map((p) => (
                  <span
                    key={p}
                    className="px-1.5 py-0.5 rounded text-xs bg-gray-800 text-gray-400 border border-gray-700"
                  >
                    {p}
                  </span>
                ))}
              </div>
            )}
          </button>
        );
      })}
    </div>
  );
}
