"use client";

import { useEffect, useState } from "react";
import { Brain, BookOpen, Link2, MessageCircle, RefreshCw } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface SessionInfo {
  session_id: string;
  started_at: string;
  summary: string;
  daichi_interactions: number;
}

interface ReviewEntry {
  id: number;
  target_type: string;
  target_id: string;
  verdict: string;
  quality_before: number | null;
  quality_after: number | null;
  created_at: string;
}

interface DialogueEntry {
  id: number;
  channel: string;
  daichi_message: string;
  created_at: string;
}

interface NodeStateEntry {
  node_name: string;
  state: string;
  reason: string;
  changed_at: string;
}

export default function BrainAlphaPage() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [reviews, setReviews] = useState<ReviewEntry[]>([]);
  const [dialogues, setDialogues] = useState<DialogueEntry[]>([]);
  const [nodeStates, setNodeStates] = useState<NodeStateEntry[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    try {
      const [nodesRes] = await Promise.all([
        apiFetch("/api/nodes/state"),
      ]);
      if (nodesRes.ok) {
        const nodesJson = await nodesRes.json();
        setNodeStates(nodesJson.nodes || []);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stateColor: Record<string, string> = {
    healthy: "text-[var(--accent-green)]",
    charlie_win11: "text-[var(--accent-amber)]",
    down: "text-[var(--accent-red)]",
  };

  const stateBadgeBg: Record<string, string> = {
    healthy: "bg-[var(--accent-green)]/10",
    charlie_win11: "bg-[var(--accent-amber)]/10",
    down: "bg-[var(--accent-red)]/10",
  };

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--accent-purple)] border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="h-6 w-6 text-[var(--accent-purple)]" />
          <h1 className="text-2xl font-bold">Brain-&alpha;</h1>
        </div>
        <button
          onClick={() => { setLoading(true); fetchData(); }}
          className="flex items-center gap-1 rounded-lg border border-[var(--border-color)] px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:text-white transition-colors"
        >
          <RefreshCw className="h-3 w-3" /> 更新
        </button>
      </div>

      {/* 接続状況 */}
      <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
        <div className="flex items-center gap-2 mb-3">
          <Link2 className="h-4 w-4 text-[var(--accent-blue)]" />
          <h2 className="text-sm font-semibold">接続状況</h2>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {nodeStates.map((ns) => (
            <div key={ns.node_name} className="rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-bold">{ns.node_name.toUpperCase()}</span>
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${stateBadgeBg[ns.state] || stateBadgeBg.down} ${stateColor[ns.state] || stateColor.down}`}>
                  {ns.state === "healthy" ? "稼働" : ns.state === "charlie_win11" ? "Win11" : ns.state}
                </span>
              </div>
              {ns.reason && <p className="mt-1 text-[10px] text-[var(--text-secondary)]">{ns.reason}</p>}
            </div>
          ))}
        </div>
      </div>

      {/* 精査レポート */}
      <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
        <div className="flex items-center gap-2 mb-3">
          <BookOpen className="h-4 w-4 text-[var(--accent-green)]" />
          <h2 className="text-sm font-semibold">精査レポート</h2>
        </div>
        {reviews.length > 0 ? (
          <div className="space-y-2">
            {reviews.map((r) => (
              <div key={r.id} className="rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2">
                <div className="flex items-center justify-between text-xs">
                  <span>{r.target_type} / {r.target_id}</span>
                  <span className={r.verdict === "approved" ? "text-[var(--accent-green)]" : "text-[var(--accent-amber)]"}>
                    {r.verdict}
                  </span>
                </div>
                {r.quality_before != null && r.quality_after != null && (
                  <p className="text-[10px] text-[var(--text-secondary)]">
                    品質: {r.quality_before.toFixed(2)} → {r.quality_after.toFixed(2)}
                  </p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="py-4 text-center text-sm text-[var(--text-secondary)]">精査レポートはまだありません</p>
        )}
      </div>

      {/* セッション記憶 */}
      <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
        <div className="flex items-center gap-2 mb-3">
          <Brain className="h-4 w-4 text-[var(--accent-amber)]" />
          <h2 className="text-sm font-semibold">セッション記憶</h2>
        </div>
        {sessions.length > 0 ? (
          <div className="space-y-2">
            {sessions.map((s) => (
              <div key={s.session_id} className="rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono">{s.session_id}</span>
                  <span className="text-[var(--text-secondary)]">{new Date(s.started_at).toLocaleString("ja-JP")}</span>
                </div>
                {s.summary && <p className="mt-1 text-xs text-[var(--text-secondary)] line-clamp-2">{s.summary}</p>}
              </div>
            ))}
          </div>
        ) : (
          <p className="py-4 text-center text-sm text-[var(--text-secondary)]">セッション記憶はまだありません</p>
        )}
      </div>

      {/* 対話ログ */}
      <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
        <div className="flex items-center gap-2 mb-3">
          <MessageCircle className="h-4 w-4 text-[var(--accent-purple)]" />
          <h2 className="text-sm font-semibold">Daichi対話ログ</h2>
        </div>
        {dialogues.length > 0 ? (
          <div className="space-y-2">
            {dialogues.map((d) => (
              <div key={d.id} className="rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2">
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-[var(--accent-purple)]">{d.channel}</span>
                  <span className="text-[var(--text-secondary)]">{new Date(d.created_at).toLocaleString("ja-JP")}</span>
                </div>
                <p className="text-xs line-clamp-2">{d.daichi_message}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="py-4 text-center text-sm text-[var(--text-secondary)]">対話ログはまだありません</p>
        )}
      </div>
    </div>
  );
}
