import { useCallback, useEffect, useState } from "react";
import { Shield, Radio } from "lucide-react";
import { AgentList, type Agent } from "./components/AgentList";
import { Terminal, type LogEntry } from "./components/Terminal";
import { MetricsPanel, type MetricPoint } from "./components/MetricsPanel";
import { ObservabilityPanel, type ObsMetrics } from "./components/ObservabilityPanel";
import { SolanaPanel } from "./components/SolanaPanel";
import { useSSE, type SSEEvent } from "./hooks/useSSE";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
const OPERATOR_TOKEN = import.meta.env.VITE_OPERATOR_TOKEN ?? "openc2-dev-token";
const MAX_LOG = 300;
const MAX_METRICS = 30;

// Expose for Terminal.tsx direct fetch calls
(window as any).__API_BASE = API_BASE;
(window as any).__TOKEN = OPERATOR_TOKEN;

let logSeq = 0;

const RISK_LABEL: Record<string, string> = {
  CRITICAL: "[!!] CRITICO",
  HIGH: "[!] ALTO",
  MEDIUM: "[~] MEDIO",
  LOW: "[i] BAJO",
  CLEAN: "[OK] LIMPIO",
};

// ---------------------------------------------------------------------------
// Output formatters — convert raw plugin results to readable text
// ---------------------------------------------------------------------------

function formatOpsecCheck(data: any): string {
  const r = (data.risk ?? data.risk_level ?? data.status ?? "?").toUpperCase();
  if (data.detected?.length > 0)
    return data.detected.map((d: any) => d.product ?? d.name ?? d.proc ?? d).join(", ");
  if (data.total_found !== undefined)
    return `${data.total_found} detectados / ${data.scanned_procs ?? "?"} procs`;
  if (data.has_active_threats !== undefined)
    return `amenazas_activas=${data.has_active_threats}`;
  if (data.sysmon_active !== undefined)
    return `activo=${data.sysmon_active}`;
  if (data.in_sandbox !== undefined)
    return `sandbox=${data.in_sandbox} | indicadores=${data.indicator_count ?? 0}`;
  if (data.tools_active?.length > 0)
    return data.tools_active.map((t: any) => t.tool ?? t.process).join(", ");
  if (data.capture_tools?.length > 0)
    return data.capture_tools.join(", ");
  if (data.warnings)
    return Object.entries(data.warnings).map(([k, v]) => `${k}=${v}`).join(" | ");
  if (data.block_rules?.length > 0)
    return `${data.block_rules.length} reglas recientes`;
  return RISK_LABEL[r] ?? r;
}

function formatOpsecOutput(output: Record<string, any>): string {
  const src = output.details ?? output;
  const risk = (output.overall_risk ?? output.risk ?? output.risk_level ?? output.status ?? "?").toUpperCase();
  const lines: string[] = [`OPSEC STATUS — ${RISK_LABEL[risk] ?? risk}`];
  lines.push("─".repeat(50));

  const checks: Array<[string, any]> = [];
  if (src.edr) checks.push(["EDR / AV", src.edr]);
  if (src.defender) checks.push(["Defender", src.defender]);
  if (src.events) checks.push(["Event Logs", src.events]);
  if (src.sysmon) checks.push(["Sysmon", src.sysmon]);
  if (src.firewall) checks.push(["Firewall", src.firewall]);
  if (src.sandbox) checks.push(["Sandbox/VM", src.sandbox]);
  if (src.net_monitor) checks.push(["Red/Captura", src.net_monitor]);

  if (checks.length > 0) {
    for (const [name, data] of checks) {
      const r = (data.risk ?? data.risk_level ?? data.status ?? "?").toUpperCase();
      const detail = formatOpsecCheck(data);
      lines.push(`  ${name.padEnd(12)} ${(RISK_LABEL[r] ?? r).padEnd(14)}  ${detail}`);
    }
  } else {
    // Single-check (edr_check alone, etc.)
    const detail = formatOpsecCheck(output);
    lines.push(`  Result: ${detail}`);
  }

  if (output.recommendations?.length) {
    lines.push("─".repeat(50));
    for (const rec of output.recommendations) lines.push(`  > ${rec}`);
  }

  return lines.join("\n");
}

function formatShellOutput(output: any): string {
  const lines: string[] = [];
  if (output.stdout?.trim()) lines.push(output.stdout.trim());
  if (output.stderr?.trim()) lines.push(`stderr: ${output.stderr.trim()}`);
  if (output.error) lines.push(`error: ${output.error}`);
  if (output.returncode !== undefined && output.returncode !== 0 && !output.error)
    lines.push(`exit code: ${output.returncode}`);
  return lines.join("\n") || "(sin salida)";
}

function formatSysinfoSummary(o: any): string {
  let t = `SYSTEM INFO\n${"─".repeat(45)}`;
  t += `\n  Host:      ${o.hostname ?? "?"}`;
  t += `\n  OS:        ${o.os ?? "?"} ${o.os_version ?? ""}`;
  t += `\n  Arch:      ${o.arch ?? "?"}`;
  t += `\n  User:      ${o.user ?? "?"}`;
  t += `\n  PID:       ${o.pid ?? "?"}`;
  if (o.cpu_count) t += `\n  CPUs:      ${o.cpu_count}`;
  if (o.cpu_percent !== undefined) t += `\n  CPU:       ${o.cpu_percent}%`;
  if (o.mem_total_gb) t += `\n  RAM:       ${o.mem_total_gb}GB (${o.mem_used_pct ?? "?"}% used)`;
  if (o.python) t += `\n  Python:    ${o.python}`;
  if (o.cwd) t += `\n  CWD:       ${o.cwd}`;
  return t;
}

function formatProcessList(procs: any[]): string {
  if (procs.length === 1 && procs[0].error) return `Error: ${procs[0].error}`;
  let t = `PROCESSES (${procs.length})\n${"─".repeat(60)}`;
  t += `\n  ${"PID".padEnd(8)} ${"CPU%".padStart(6)}  ${"MEM%".padStart(6)}   USER / NAME`;
  for (const p of procs) {
    const pid = String(p.pid ?? "?").padEnd(8);
    const cpu = String((p.cpu_percent ?? 0).toFixed(1)).padStart(6);
    const mem = String((p.memory_percent ?? 0).toFixed(1)).padStart(6);
    const usr = p.username ? `${p.username}/` : "";
    t += `\n  ${pid} ${cpu}  ${mem}   ${usr}${p.name ?? "?"}`;
  }
  return t;
}

function formatNetworkOutput(output: any): string {
  if (output.error) return `Error: ${output.error}`;
  const conns: any[] = output.connections ?? [];
  let t = `NETWORK — ${conns.length} connections\n${"─".repeat(70)}`;
  t += `\n  ${"LOCAL".padEnd(22)} ${"REMOTE".padEnd(22)} ${"STATUS".padEnd(13)} PID`;
  for (const c of conns.slice(0, 30)) {
    t += `\n  ${(c.laddr ?? "").padEnd(22)} ${(c.raddr ?? "-").padEnd(22)} ${(c.status ?? "").padEnd(13)} ${c.pid ?? "?"}`;
  }
  if (conns.length > 30) t += `\n  ... +${conns.length - 30} more`;
  const ifaces = output.interfaces ?? {};
  const names = Object.keys(ifaces);
  if (names.length > 0) {
    t += `\n\n  INTERFACES (${names.length})`;
    for (const n of names.slice(0, 10)) {
      const addrs = ifaces[n].filter((a: any) => !a.address?.includes(":")).map((a: any) => a.address).join(", ");
      if (addrs) t += `\n  ${n}: ${addrs}`;
    }
  }
  return t;
}

function formatEnvVars(output: any): string {
  const keys = Object.keys(output).sort();
  let t = `ENVIRONMENT (${keys.length} vars)\n${"─".repeat(55)}`;
  for (const k of keys) {
    const v = String(output[k]);
    t += `\n  ${k}=${v.length > 70 ? v.slice(0, 70) + "..." : v}`;
  }
  return t;
}

function formatResultOutput(output: any): { text: string; risk?: LogEntry["riskLevel"] } {
  if (output == null) return { text: "(null)" };
  if (typeof output === "string") return { text: output };
  if (typeof output !== "object") return { text: String(output) };

  // Shell output (has cmd field)
  if ("cmd" in output)
    return { text: formatShellOutput(output) };

  // OPSEC full_report (has overall_risk + details)
  if ("overall_risk" in output && "details" in output)
    return { text: formatOpsecOutput(output), risk: extractRiskLevel(output) };

  // OPSEC single checks
  if ("edr" in output || "defender" in output || "sysmon" in output ||
      "net_monitor" in output || "sandbox" in output ||
      (("risk" in output || "status" in output) &&
       ("detected" in output || "in_sandbox" in output ||
        "has_active_threats" in output || "tools_active" in output ||
        "sysmon_active" in output || "warnings" in output)))
    return { text: formatOpsecOutput(output), risk: extractRiskLevel(output) };

  // Sysinfo summary
  if ("hostname" in output && "os" in output && "arch" in output)
    return { text: formatSysinfoSummary(output) };

  // Process list
  if (Array.isArray(output) && output.length > 0 && "pid" in (output[0] ?? {}))
    return { text: formatProcessList(output) };

  // Network output
  if ("connections" in output && "interfaces" in output)
    return { text: formatNetworkOutput(output) };

  // Env vars (many string values)
  const keys = Object.keys(output);
  if (keys.length > 5 && keys.every(k => typeof output[k] === "string"))
    return { text: formatEnvVars(output) };

  // Fallback — still JSON but compact
  return { text: JSON.stringify(output, null, 2) };
}

function extractRiskLevel(output: any): LogEntry["riskLevel"] | undefined {
  if (!output || typeof output !== "object") return undefined;
  const raw = (
    output.overall_risk ?? output.risk ?? output.risk_level ?? output.status ?? ""
  ).toUpperCase();
  if (["CRITICAL", "HIGH", "MEDIUM", "LOW", "CLEAN"].includes(raw))
    return raw as LogEntry["riskLevel"];
  return undefined;
}

function makeLog(
  topic: string,
  type: LogEntry["type"],
  content: string,
  agentId?: string,
  riskLevel?: LogEntry["riskLevel"],
): LogEntry {
  return {
    id: `${Date.now()}-${++logSeq}`,
    ts: Date.now() / 1000,
    topic,
    type,
    content,
    agentId,
    riskLevel,
  };
}

export default function App() {
  const [agents, setAgents] = useState<Record<string, Agent>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [metricsHistory, setMetricsHistory] = useState<Record<string, MetricPoint[]>>({});
  const [connected, setConnected] = useState(false);
  const [obsMetrics, setObsMetrics] = useState<ObsMetrics | null>(null);

  const addLog = useCallback((entry: LogEntry) => {
    setLogs((prev) => [...prev.slice(-MAX_LOG), entry]);
  }, []);

  // Fetch initial agent list
  useEffect(() => {
    fetch(`${API_BASE}/api/agents`, {
      headers: { "X-Operator-Token": OPERATOR_TOKEN },
    })
      .then((r) => r.json())
      .then((data: Agent[]) => {
        const map: Record<string, Agent> = {};
        data.forEach((a) => (map[a.agent_id] = a));
        setAgents(map);
        setConnected(true);
        addLog(makeLog("system", "success", `Loaded ${data.length} agent(s) from server`));
      })
      .catch(() => {
        addLog(makeLog("system", "warn", "Server not reachable — running in demo mode"));
        injectDemoAgents();
      });
  }, []);

  function injectDemoAgents() {
    const demo: Agent[] = [
      {
        agent_id: "aaaabbbb-0000-0000-0000-000000000001",
        hostname: "WIN-DEMO-01",
        os: "Windows",
        arch: "x86_64",
        user: "operator",
        capabilities: ["shell", "sysinfo"],
        plugins: ["shell", "sysinfo"],
        first_seen: Date.now() / 1000 - 300,
        last_seen: Date.now() / 1000,
        connected: true,
        metrics: { cpu: 12.4, mem: 58.1, uptime: 300 },
      },
      {
        agent_id: "ccccdddd-0000-0000-0000-000000000002",
        hostname: "LINUX-LAB-02",
        os: "Linux",
        arch: "x86_64",
        user: "root",
        capabilities: ["shell", "sysinfo"],
        plugins: ["shell", "sysinfo"],
        first_seen: Date.now() / 1000 - 120,
        last_seen: Date.now() / 1000 - 8,
        connected: true,
        metrics: { cpu: 3.2, mem: 34.9, uptime: 120 },
      },
    ];
    const map: Record<string, Agent> = {};
    demo.forEach((a) => (map[a.agent_id] = a));
    setAgents(map);

    // Simulate heartbeat ticks in demo mode
    const interval = setInterval(() => {
      const ts = new Date().toLocaleTimeString("en-US", { hour12: false });
      setAgents((prev) => {
        const next = { ...prev };
        Object.values(next).forEach((a) => {
          a.metrics = {
            cpu: Math.max(0, Math.min(100, (a.metrics?.cpu ?? 10) + (Math.random() - 0.5) * 8)),
            mem: Math.max(0, Math.min(100, (a.metrics?.mem ?? 40) + (Math.random() - 0.5) * 2)),
            uptime: (a.metrics?.uptime ?? 0) + 10,
          };
          a.last_seen = Date.now() / 1000;
        });
        return next;
      });
      setMetricsHistory((prev) => {
        const next = { ...prev };
        demo.forEach((a) => {
          const existing = next[a.agent_id] ?? [];
          const agent = agents[a.agent_id] ?? a;
          const pt: MetricPoint = {
            ts,
            cpu: agent.metrics?.cpu ?? 0,
            mem: agent.metrics?.mem ?? 0,
          };
          next[a.agent_id] = [...existing.slice(-MAX_METRICS + 1), pt];
        });
        return next;
      });
    }, 5000);
    return () => clearInterval(interval);
  }

  // SSE handler
  const handleSSE = useCallback(
    (ev: SSEEvent) => {
      setConnected(true);
      const { topic, data, ts } = ev;

      if (topic.includes("registered")) {
        const a = data as unknown as Agent;
        setAgents((prev) => ({ ...prev, [a.agent_id]: a }));
        addLog(makeLog("connect", "success", `Agent online: ${a.hostname} (${a.agent_id.slice(0, 8)})`, a.agent_id));
      } else if (topic.includes("disconnected")) {
        const agentId = (data as any).agent_id as string;
        setAgents((prev) => {
          const copy = { ...prev };
          if (copy[agentId]) copy[agentId] = { ...copy[agentId], connected: false };
          return copy;
        });
        addLog(makeLog("disconnect", "warn", `Agent offline: ${agentId.slice(0, 8)}`, agentId));
      } else if (topic.includes("heartbeat")) {
        const agentId = (data as any).agent_id as string;
        const metrics = (data as any).metrics ?? {};
        setAgents((prev) => {
          if (!prev[agentId]) return prev;
          return {
            ...prev,
            [agentId]: { ...prev[agentId], metrics, last_seen: ts, connected: true },
          };
        });
        const time = new Date(ts * 1000).toLocaleTimeString("en-US", { hour12: false });
        setMetricsHistory((prev) => {
          const existing = prev[agentId] ?? [];
          const pt: MetricPoint = {
            ts: time,
            cpu: metrics.cpu ?? 0,
            mem: metrics.mem ?? 0,
          };
          return { ...prev, [agentId]: [...existing.slice(-MAX_METRICS + 1), pt] };
        });
      } else if (topic.includes("result")) {
        const agentId = (data as any).agent_id as string;
        const ok = (data as any).ok;
        const output = (data as any).output;
        const taskId = (data as any).task_id?.slice(0, 8) ?? "?";
        let content = `task:${taskId} ${ok ? "OK" : "ERR"} ${(data as any).duration_ms ?? 0}ms`;
        let riskLevel: LogEntry["riskLevel"] | undefined;
        if (!ok && (data as any).error) content += `\nerror: ${(data as any).error}`;
        if (output != null) {
          const fmt = formatResultOutput(output);
          content += `\n${fmt.text}`;
          riskLevel = fmt.risk;
        }
        addLog(makeLog("result", ok ? "result" : "error", content, agentId, riskLevel));
      } else if (topic.includes("task_enqueued")) {
        const agentId = (data as any).agent_id as string;
        addLog(makeLog("task", "info", `Task queued → ${agentId.slice(0, 8)}`, agentId));
      } else if (topic.includes("event")) {
        addLog(makeLog("event", "info", JSON.stringify(data).slice(0, 200)));
      } else if (topic === "metrics.update") {
        setObsMetrics(data as unknown as ObsMetrics);
      }
    },
    [addLog]
  );

  useSSE(handleSSE);

  // Send task to backend
  async function sendTask(
    plugin: string,
    action: string,
    args: Record<string, unknown>
  ) {
    // Handle local commands (doctor, snapshot, audit) — result already fetched by Terminal
    if (plugin === "__local__") {
      const data = args as Record<string, any>;
      if (action === "doctor_result") {
        const status = data.status ?? "UNKNOWN";
        const issues = (data.issues ?? []).join("; ") || "None";
        const checks = data.checks ?? {};
        let content = `DOCTOR DIAGNOSTIC — ${status}\n${"─".repeat(50)}`;
        content += `\n  Crypto:     ${checks.crypto?.status ?? "?"}`;
        content += `\n  Agents:     ${checks.agents?.connected ?? 0} connected / ${checks.agents?.total ?? 0} total`;
        content += `\n  Channels:   WS=${checks.channels?.websocket?.status ?? "?"} DNS=${checks.channels?.dns?.status ?? "?"}`;
        content += `\n  Audit:      ${checks.audit_trail?.blocks ?? 0} blocks, valid=${checks.audit_trail?.integrity?.valid ?? "?"}`;
        content += `\n  Solana:     ${checks.solana?.enabled ? "active" : "off"}`;
        content += `\n  Plugins:    ${(checks.plugins_available ?? []).join(", ")}`;
        if (issues !== "None") content += `\n${"─".repeat(50)}\n  Issues: ${issues}`;
        addLog(makeLog("doctor", status === "HEALTHY" ? "success" : "warn", content, selected ?? undefined));
      } else if (action === "snapshot_result") {
        const id = data.snapshot_id ?? "?";
        const total = data.total_snapshots ?? "?";
        addLog(makeLog("snapshot", "success", `Snapshot #${id} captured (${total} total)`, selected ?? undefined));
      } else if (action === "diff_result") {
        const changes = data.changes ?? {};
        const fields = data.changed_fields ?? [];
        let content = `SNAPSHOT DIFF — ${data.elapsed_s ?? "?"}s elapsed\n${"─".repeat(50)}`;
        if (fields.length === 0) {
          content += "\n  No changes detected";
        } else {
          for (const f of fields) {
            const c = changes[f];
            content += `\n  ${f}: ${JSON.stringify(c.before)} → ${JSON.stringify(c.after)}`;
          }
        }
        addLog(makeLog("snapshot", fields.length > 0 ? "warn" : "success", content, selected ?? undefined));
      } else if (action === "audit_result") {
        const valid = data.chain_valid;
        let content = `AUDIT VERIFY\n${"─".repeat(50)}`;
        content += `\n  Chain valid:      ${valid ? "YES" : "NO — TAMPERED"}`;
        content += `\n  Total blocks:     ${data.total_blocks ?? 0}`;
        content += `\n  Solana anchored:  ${data.solana_anchored ?? 0}`;
        content += `\n  Pending anchor:   ${data.solana_pending ?? 0}`;
        if ((data.corrupt_blocks ?? []).length > 0)
          content += `\n  Corrupt blocks:   ${data.corrupt_blocks.join(", ")}`;
        addLog(makeLog("audit", valid ? "success" : "error", content, selected ?? undefined));
      }
      return;
    }

    if (!selected) return;
    addLog(makeLog("task", "info", `→ ${plugin}.${action} ${JSON.stringify(args)}`, selected));
    try {
      const resp = await fetch(`${API_BASE}/api/agents/${selected}/task`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Operator-Token": OPERATOR_TOKEN,
        },
        body: JSON.stringify({ plugin, action, args, timeout: 30 }),
      });
      if (!resp.ok) {
        const err = await resp.text();
        addLog(makeLog("task", "error", `HTTP ${resp.status}: ${err}`, selected));
      }
    } catch (e) {
      addLog(makeLog("task", "warn", `[demo] task would run: ${plugin}.${action}(${JSON.stringify(args)})`, selected ?? undefined));
    }
  }

  const agentList = Object.values(agents);
  const liveCount = agentList.filter((a) => a.connected).length;
  const selectedHistory = selected ? (metricsHistory[selected] ?? []) : [];

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-gray-200 font-mono flex flex-col">
      {/* Top nav */}
      <header className="flex items-center justify-between px-6 py-3 border-b border-gray-800/60 bg-gray-950/80 backdrop-blur">
        <div className="flex items-center gap-3">
          <Shield className="w-5 h-5 text-cyan-400" />
          <span className="text-lg font-bold text-cyan-400 glow-accent tracking-widest">
            OPENC2
          </span>
          <span className="text-xs text-gray-600 ml-1">operator console v1.0</span>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-1.5">
            <Radio className="w-3 h-3 text-green-400 animate-pulse" />
            <span className="text-green-400">{liveCount} live</span>
            <span className="text-gray-600">/ {agentList.length} total</span>
          </div>
          <div
            className={`flex items-center gap-1.5 ${
              connected ? "text-green-600" : "text-yellow-600"
            }`}
          >
            <div
              className={`w-1.5 h-1.5 rounded-full ${
                connected ? "bg-green-500" : "bg-yellow-500 animate-pulse"
              }`}
            />
            {connected ? "server connected" : "demo mode"}
          </div>
        </div>
      </header>

      {/* Main layout */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: agent list */}
        <aside className="w-72 border-r border-gray-800/60 bg-gray-950/40 flex flex-col overflow-hidden">
          <div className="px-4 py-2 border-b border-gray-800/60">
            <span className="text-xs text-gray-600 uppercase tracking-widest">Agents</span>
          </div>
          <div className="flex-1 overflow-y-auto p-3">
            <AgentList
              agents={agentList}
              selected={selected}
              onSelect={setSelected}
            />
          </div>
        </aside>

        {/* Center: terminal */}
        <main className="flex-1 flex flex-col overflow-hidden p-4">
          <Terminal
            logs={logs}
            selectedAgent={selected}
            onSendTask={sendTask}
            onClear={() => setLogs([])}
          />
        </main>

        {/* Right: metrics + observability */}
        <aside className="w-72 border-l border-gray-800/60 bg-gray-950/40 overflow-y-auto p-4 flex flex-col gap-6">
          <MetricsPanel
            agentId={selected}
            history={selectedHistory}
            totalAgents={agentList.length}
            liveAgents={liveCount}
          />
          <div className="border-t border-gray-800/60 pt-4">
            <ObservabilityPanel metrics={obsMetrics} />
          </div>
          <div className="border-t border-gray-800/60 pt-4">
            <SolanaPanel />
          </div>
        </aside>
      </div>

      {/* Footer */}
      <footer className="px-6 py-2 border-t border-gray-800/60 text-xs text-gray-700 flex justify-between">
        <span>OpenC2 v1.0 — lab environment only</span>
        <span>encrypted · pub/sub · multi-channel</span>
      </footer>
    </div>
  );
}
