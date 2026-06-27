import { useEffect, useState } from "react";
import { Link } from "lucide-react";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
const OPERATOR_TOKEN = import.meta.env.VITE_OPERATOR_TOKEN ?? "openc2-dev-token";

type SigEntry = { block_id: number; sig: string; explorer: string };

type SolanaInfo = {
  enabled: boolean;
  network?: string;
  pubkey?: string;
  explorer?: string;
  anchored_blocks?: number;
  recent_signatures?: SigEntry[];
  message?: string;
  error?: string;
};

export function SolanaPanel() {
  const [info, setInfo] = useState<SolanaInfo | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/solana`, {
      headers: { "X-Operator-Token": OPERATOR_TOKEN },
    })
      .then((r) => r.json())
      .then(setInfo)
      .catch(() => setInfo({ enabled: false, message: "Server unreachable" }));

    const id = setInterval(() => {
      fetch(`${API_BASE}/api/solana`, {
        headers: { "X-Operator-Token": OPERATOR_TOKEN },
      })
        .then((r) => r.json())
        .then(setInfo)
        .catch(() => {});
    }, 30_000);

    return () => clearInterval(id);
  }, []);

  if (!info) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-600 uppercase tracking-widest">
          Solana Devnet
        </span>
        <span
          className={`text-xs px-1.5 py-0.5 rounded ${
            info.enabled
              ? "bg-purple-900/50 text-purple-300"
              : "bg-gray-800 text-gray-600"
          }`}
        >
          {info.enabled ? "active" : "off"}
        </span>
      </div>

      {!info.enabled && (
        <p className="text-xs text-gray-600">{info.message}</p>
      )}

      {info.enabled && (
        <div className="space-y-2 text-xs font-mono">
          {info.error ? (
            <p className="text-red-400">{info.error}</p>
          ) : (
            <>
              <div className="text-gray-500">
                <span className="text-gray-600">wallet </span>
                <span className="text-purple-400 break-all">
                  {info.pubkey?.slice(0, 20)}…
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-600">anchored blocks</span>
                <span className="text-purple-300 font-bold">
                  {info.anchored_blocks ?? 0}
                </span>
              </div>
              <a
                href={info.explorer}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1 text-gray-700 hover:text-purple-400 transition-colors"
              >
                <Link className="w-3 h-3" />
                <span>explorer</span>
              </a>
            </>
          )}

          {(info.recent_signatures?.length ?? 0) > 0 && (
            <div className="pt-1 border-t border-gray-800/60 space-y-1">
              <span className="text-gray-700 text-[10px] uppercase tracking-wider">
                Recent Anchors
              </span>
              {info.recent_signatures!.slice(0, 5).map((s) => (
                <a
                  key={s.sig}
                  href={s.explorer}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center justify-between gap-2 hover:text-purple-400 transition-colors"
                >
                  <span className="text-gray-600">#{s.block_id}</span>
                  <span className="text-gray-700 truncate text-[10px]">
                    {s.sig.slice(0, 16)}…
                  </span>
                  <Link className="w-2.5 h-2.5 shrink-0 text-gray-700" />
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
