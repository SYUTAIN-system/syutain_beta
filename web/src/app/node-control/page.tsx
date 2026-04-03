"use client";

import { useEffect, useState, useCallback } from "react";
import { Server, Monitor, RefreshCw, History, Wrench } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface NodeState {
  node_name: string;
  state: string;
  reason: string | null;
  changed_by: string | null;
  changed_at: string | null;
}

interface HistoryEntry {
  event_type: string;
  payload: Record<string, string>;
  created_at: string;
}

const stateConfig: Record<string, { label: string; color: string; bg: string; dot: string }> = {
  healthy: { label: "稼働中", color: "text-[var(--accent-green)]", bg: "bg-[var(--accent-green)]/10", dot: "bg-[var(--accent-green)]" },
  degraded: { label: "一部異常", color: "text-[var(--accent-amber)]", bg: "bg-[var(--accent-amber)]/10", dot: "bg-[var(--accent-amber)]" },
  charlie_win11: { label: "Win11", color: "text-[var(--accent-amber)]", bg: "bg-[var(--accent-amber)]/10", dot: "bg-[var(--accent-amber)]" },
  recovering: { label: "復旧中", color: "text-[var(--accent-blue)]", bg: "bg-[var(--accent-blue)]/10", dot: "bg-[var(--accent-blue)]" },
  down: { label: "停止", color: "text-[var(--accent-red)]", bg: "bg-[var(--accent-red)]/10", dot: "bg-[var(--accent-red)]" },
};

const nodeRoles: Record<string, string> = {
  alpha: "Brain-α + Brain-βインフラ（推論しない）",
  bravo: "LLM主力 + ブラウザ操作（RTX 5070）",
  charlie: "副推論 + コンテンツ生成（RTX 3080）",
  delta: "監視 + 軽量タスク（GTX 980Ti）",
};

const nodeModels: Record<string, string> = {
  alpha: "推論なし（Brain-α専用）",
  bravo: "Nemotron 9B JP + Qwen3.5-9B",
  charlie: "Nemotron 9B JP + Qwen3.5-9B",
  delta: "Qwen3.5-4B",
};

export default function NodeControlPage() {
  const [nodes, setNodes] = useState<NodeState[]>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [charlieMode, setCharlieMode] = useState<string>("ubuntu");
  const [switching, setSwitching] = useState(false);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);
  const [healStats, setHealStats] = useState<{total_24h: number; success_rate_24h: number; recent: {id: number; error_type: string; fix_strategy: string; fix_result: string; created_at: string}[]} | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [stateRes, charlieRes, historyRes, healRes] = await Promise.all([
        apiFetch("/api/nodes/state"),
        apiFetch("/api/nodes/charlie/mode"),
        apiFetch("/api/nodes/state/history?limit=20"),
        apiFetch("/api/self-healing/stats").catch(() => null),
      ]);
      if (stateRes.ok) {
        const json = await stateRes.json();
        setNodes(json.nodes || []);
      }
      if (charlieRes.ok) {
        const json = await charlieRes.json();
        setCharlieMode(json.mode || "ubuntu");
      }
      if (historyRes.ok) {
        const json = await historyRes.json();
        setHistory(json.history || []);
      }
      if (healRes && healRes.ok) {
        setHealStats(await healRes.json());
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const toggleCharlieMode = async () => {
    const newMode = charlieMode === "win11" ? "ubuntu" : "win11";
    setSwitching(true);
    try {
      const res = await apiFetch("/api/nodes/charlie/mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: newMode }),
      });
      if (res.ok) {
        setCharlieMode(newMode);
        setToast({ msg: `CHARLIE → ${newMode === "win11" ? "Win11" : "Ubuntu"}モードに切替`, type: "success" });
        fetchData();
      } else {
        const err = await res.json().catch(() => ({}));
        setToast({ msg: err.detail || "切替に失敗しました", type: "error" });
      }
    } catch {
      setToast({ msg: "通信エラー", type: "error" });
    } finally {
      setSwitching(false);
    }
  };

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--accent-purple)] border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Toast */}
      {toast && (
        <div
          className="fixed top-4 right-4 z-50 rounded-lg px-4 py-3 shadow-lg text-sm text-white"
          style={{ backgroundColor: toast.type === "success" ? "var(--accent-green)" : "var(--accent-red)" }}
        >
          {toast.msg}
        </div>
      )}

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Server className="h-6 w-6 text-[var(--accent-purple)]" />
          <h1 className="text-2xl font-bold">ノード制御</h1>
        </div>
        <button
          onClick={() => { setLoading(true); fetchData(); }}
          className="flex items-center gap-1 rounded-lg border border-[var(--border-color)] px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:text-white transition-colors"
        >
          <RefreshCw className="h-3 w-3" /> 更新
        </button>
      </div>

      {/* 4ノード詳細 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {nodes.map((n) => {
          const cfg = stateConfig[n.state] || stateConfig.down;
          return (
            <div key={n.node_name} className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <Server className="h-4 w-4 text-[var(--accent-purple)]" />
                  <span className="text-lg font-bold">{n.node_name.toUpperCase()}</span>
                </div>
                <span className={`flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${cfg.bg} ${cfg.color}`}>
                  <span className={`h-2 w-2 rounded-full ${cfg.dot}`} />
                  {cfg.label}
                </span>
              </div>
              <p className="text-xs text-[var(--text-secondary)] mb-1">{nodeRoles[n.node_name] || ""}</p>
              <p className="text-xs text-[var(--text-secondary)]">モデル: {nodeModels[n.node_name] || "N/A"}</p>
              {n.reason && <p className="mt-1 text-[10px] text-[var(--text-secondary)]">理由: {n.reason}</p>}
              {n.changed_at && (
                <p className="text-[10px] text-[var(--text-secondary)]">
                  更新: {new Date(n.changed_at).toLocaleString("ja-JP")} ({n.changed_by || "system"})
                </p>
              )}
            </div>
          );
        })}
      </div>

      {/* CHARLIE Win11 制御 */}
      <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
        <div className="flex items-center gap-2 mb-3">
          <Monitor className="h-4 w-4 text-[var(--accent-amber)]" />
          <h2 className="text-sm font-semibold">CHARLIE Win11 制御</h2>
        </div>
        <div className="flex items-center justify-between rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-4 py-3">
          <div>
            <p className="text-sm font-medium">
              現在のモード:{" "}
              <span className={charlieMode === "win11" ? "text-[var(--accent-amber)]" : "text-[var(--accent-green)]"}>
                {charlieMode === "win11" ? "Win11（島原使用中）" : "Ubuntu（推論稼働）"}
              </span>
            </p>
            <p className="text-xs text-[var(--text-secondary)] mt-0.5">
              {charlieMode === "win11"
                ? "全タスクはBRAVO/DELTAに振替されています"
                : "CHARLIEは推論ノードとして稼働中です"}
            </p>
          </div>
          <button
            onClick={toggleCharlieMode}
            disabled={switching}
            className={`rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors disabled:opacity-50 ${
              charlieMode === "win11"
                ? "bg-[var(--accent-green)] hover:bg-[var(--accent-green)]/80"
                : "bg-[var(--accent-amber)] hover:bg-[var(--accent-amber)]/80"
            }`}
          >
            {switching ? "切替中..." : charlieMode === "win11" ? "Ubuntu復帰" : "Win11切替"}
          </button>
        </div>
      </div>

      {/* 自律修復 */}
      {healStats && (
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2 mb-3">
            <Wrench className="h-4 w-4 text-[var(--accent-blue)]" />
            <h2 className="text-sm font-semibold">自律修復</h2>
            <div className="ml-auto flex items-center gap-3 text-xs">
              <span>24h: <span className="font-bold">{healStats.total_24h}</span>件</span>
              <span>成功率: <span className={`font-bold ${healStats.success_rate_24h >= 80 ? "text-[var(--accent-green)]" : "text-[var(--accent-amber)]"}`}>{healStats.success_rate_24h}%</span></span>
            </div>
          </div>
          {healStats.recent && healStats.recent.length > 0 ? (
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {healStats.recent.slice(0, 10).map((r) => (
                <div key={r.id} className="flex items-center justify-between rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2 text-xs">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={`h-2 w-2 rounded-full flex-shrink-0 ${r.fix_result === "success" ? "bg-[var(--accent-green)]" : r.fix_result === "attempted" ? "bg-[var(--accent-amber)]" : "bg-[var(--accent-red)]"}`} />
                    <span className="truncate">{r.error_type}</span>
                    <span className="text-[var(--text-secondary)]">→ {r.fix_strategy}</span>
                  </div>
                  <span className="text-[var(--text-secondary)] flex-shrink-0 ml-2">
                    {r.created_at ? new Date(r.created_at).toLocaleString("ja-JP") : ""}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="py-3 text-center text-xs text-[var(--text-secondary)]">修復履歴なし</p>
          )}
        </div>
      )}

      {/* 変更履歴 */}
      <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
        <div className="flex items-center gap-2 mb-3">
          <History className="h-4 w-4 text-[var(--text-secondary)]" />
          <h2 className="text-sm font-semibold">変更履歴</h2>
        </div>
        {history.length > 0 ? (
          <div className="space-y-2">
            {history.map((h, i) => (
              <div key={i} className="flex items-center justify-between rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2 text-xs">
                <div>
                  <span className="font-mono">{h.event_type}</span>
                  {h.payload?.reason && <span className="ml-2 text-[var(--text-secondary)]">{h.payload.reason}</span>}
                </div>
                <span className="text-[var(--text-secondary)]">{h.created_at ? new Date(h.created_at).toLocaleString("ja-JP") : ""}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="py-4 text-center text-sm text-[var(--text-secondary)]">変更履歴はまだありません</p>
        )}
      </div>
    </div>
  );
}
