"use client";

import { useEffect, useState, useCallback } from "react";
import { Brain, BookOpen, Link2, MessageCircle, RefreshCw, AlertTriangle, Play, ChevronDown, ChevronUp, Database, ArrowUpRight, ArrowDownLeft, Scale } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface NodeStateEntry {
  node_name: string;
  state: string;
  reason: string;
  changed_at: string;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
interface ReviewReport {
  id: number;
  summary: string;
  recommended_actions: string[];
  warnings: string[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  phases: Record<string, any>;
  generated_at: string;
}

interface ReportListItem {
  id: number;
  summary: string;
  actions: string[];
  generated_at: string;
}

export default function BrainAlphaPage() {
  const [nodeStates, setNodeStates] = useState<NodeStateEntry[]>([]);
  const [latestReport, setLatestReport] = useState<ReviewReport | null>(null);
  const [pastReports, setPastReports] = useState<ReportListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [phasesOpen, setPhasesOpen] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [sessions, setSessions] = useState<any[]>([]);
  const [personaStats, setPersonaStats] = useState<{total: number; categories: {category: string; count: number; embedded: number}[]} | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [handoffs, setHandoffs] = useState<any[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [queue, setQueue] = useState<any[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [crossEvals, setCrossEvals] = useState<any[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [dialogues, setDialogues] = useState<any[]>([]);

  const fetchData = useCallback(async () => {
    try {
      const [nodesRes, reportRes, reportsRes, sessionsRes, personaRes, handoffRes, queueRes, crossEvalRes, dialoguesRes] = await Promise.all([
        apiFetch("/api/nodes/state"),
        apiFetch("/api/brain-alpha/latest-report"),
        apiFetch("/api/brain-alpha/reports?limit=5"),
        apiFetch("/api/brain-alpha/sessions?limit=10"),
        apiFetch("/api/brain-alpha/persona-stats"),
        apiFetch("/api/brain-alpha/handoffs?limit=20"),
        apiFetch("/api/brain-alpha/queue?status=pending"),
        apiFetch("/api/brain-alpha/cross-evaluations?limit=10"),
        apiFetch("/api/brain-alpha/dialogues?limit=10"),
      ]);
      if (nodesRes.ok) setNodeStates((await nodesRes.json()).nodes || []);
      if (reportRes.ok) {
        const d = await reportRes.json();
        setLatestReport(d.report || null);
      }
      if (reportsRes.ok) {
        const d = await reportsRes.json();
        setPastReports(d.reports || []);
      }
      if (sessionsRes.ok) {
        const d = await sessionsRes.json();
        setSessions(d.sessions || []);
      }
      if (personaRes.ok) {
        setPersonaStats(await personaRes.json());
      }
      if (handoffRes.ok) setHandoffs((await handoffRes.json()).handoffs || []);
      if (queueRes.ok) setQueue((await queueRes.json()).queue || []);
      if (crossEvalRes.ok) setCrossEvals((await crossEvalRes.json()).evaluations || []);
      if (dialoguesRes.ok) setDialogues((await dialoguesRes.json()).dialogues || []);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const runReview = async () => {
    setRunning(true);
    try {
      const res = await apiFetch("/api/brain-alpha/run-review", { method: "POST" });
      if (res.ok) {
        await fetchData();
      }
    } catch {
      // ignore
    } finally {
      setRunning(false);
    }
  };

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
        <div className="flex items-center gap-2">
          <button
            onClick={runReview}
            disabled={running}
            className="flex items-center gap-1 rounded-lg bg-[var(--accent-purple)] px-3 py-1.5 text-xs text-white hover:bg-[var(--accent-purple)]/80 transition-colors disabled:opacity-50"
          >
            {running ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
            {running ? "精査中..." : "精査実行"}
          </button>
          <button
            onClick={() => { setLoading(true); fetchData(); }}
            className="flex items-center gap-1 rounded-lg border border-[var(--border-color)] px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:text-white transition-colors"
          >
            <RefreshCw className="h-3 w-3" /> 更新
          </button>
        </div>
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
            </div>
          ))}
        </div>
      </div>

      {/* 最新精査レポート */}
      <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
        <div className="flex items-center gap-2 mb-3">
          <BookOpen className="h-4 w-4 text-[var(--accent-green)]" />
          <h2 className="text-sm font-semibold">精査レポート</h2>
          {latestReport && (
            <span className="ml-auto text-[10px] text-[var(--text-secondary)]">
              {new Date(latestReport.generated_at).toLocaleString("ja-JP")}
            </span>
          )}
        </div>

        {latestReport ? (
          <div className="space-y-3">
            {/* サマリー */}
            <p className="text-sm font-medium">{latestReport.summary}</p>

            {/* 警告 */}
            {latestReport.warnings.length > 0 && (
              <div className="space-y-1">
                {latestReport.warnings.map((w, i) => (
                  <div key={i} className="flex items-start gap-2 rounded-md bg-[var(--accent-amber)]/10 px-3 py-2 text-xs text-[var(--accent-amber)]">
                    <AlertTriangle className="h-3 w-3 mt-0.5 flex-shrink-0" />
                    {w}
                  </div>
                ))}
              </div>
            )}

            {/* 推奨アクション */}
            {latestReport.recommended_actions.length > 0 && (
              <div>
                <p className="text-xs text-[var(--text-secondary)] mb-1">推奨アクション</p>
                <div className="space-y-1">
                  {latestReport.recommended_actions.map((a, i) => (
                    <div key={i} className="flex items-start gap-2 rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2 text-xs">
                      <span className="text-[var(--accent-purple)] font-bold flex-shrink-0">{i + 1}.</span>
                      {a}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Phase詳細 */}
            <button
              onClick={() => setPhasesOpen(!phasesOpen)}
              className="flex items-center gap-1 text-xs text-[var(--text-secondary)] hover:text-white transition-colors"
            >
              {phasesOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              Phase詳細 (8段階)
            </button>

            {phasesOpen && latestReport.phases && (
              <div className="space-y-2">
                {Object.entries(latestReport.phases).map(([key, data]) => {
                  const labels: Record<string, string> = {
                    "1_session_restore": "1. セッション復元",
                    "2_daichi_thoughts": "2. Daichi思考",
                    "3_intel_review": "3. 情報収集",
                    "4_artifacts": "4. 成果物",
                    "5_quality_trend": "5. 品質推移",
                    "6_errors": "6. エラー分析",
                    "7_revenue": "7. 収益",
                    "8_trace_queue": "8. トレース/キュー",
                  };
                  return (
                    <details key={key} className="rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)]">
                      <summary className="px-3 py-2 text-xs font-medium cursor-pointer">{labels[key] || key}</summary>
                      <pre className="px-3 pb-2 text-[10px] text-[var(--text-secondary)] whitespace-pre-wrap break-all">
                        {JSON.stringify(data, null, 2)}
                      </pre>
                    </details>
                  );
                })}
              </div>
            )}
          </div>
        ) : (
          <div className="py-4 text-center">
            <p className="text-sm text-[var(--text-secondary)] mb-2">精査レポートはまだありません</p>
            <button
              onClick={runReview}
              disabled={running}
              className="rounded-lg bg-[var(--accent-purple)] px-4 py-2 text-xs text-white disabled:opacity-50"
            >
              初回精査を実行
            </button>
          </div>
        )}
      </div>

      {/* 過去レポート */}
      {pastReports.length > 1 && (
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2 mb-3">
            <MessageCircle className="h-4 w-4 text-[var(--text-secondary)]" />
            <h2 className="text-sm font-semibold">過去のレポート</h2>
          </div>
          <div className="space-y-1">
            {pastReports.slice(1).map((r) => (
              <div key={r.id} className="flex items-center justify-between rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2 text-xs">
                <span className="truncate flex-1">{r.summary}</span>
                <span className="ml-2 text-[var(--text-secondary)] flex-shrink-0">
                  {r.generated_at ? new Date(r.generated_at).toLocaleString("ja-JP") : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      {/* エスカレーション / 指令 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {/* claude_code_queue */}
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2 mb-3">
            <ArrowUpRight className="h-4 w-4 text-[var(--accent-amber)]" />
            <h2 className="text-sm font-semibold">エスカレーション (β→α)</h2>
            {queue.length > 0 && <span className="ml-auto rounded-full bg-[var(--accent-amber)]/20 px-2 py-0.5 text-[10px] text-[var(--accent-amber)]">{queue.length}件</span>}
          </div>
          {queue.length > 0 ? (
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {queue.map((q: {id: number; priority: string; category: string; description: string; source_agent: string; created_at: string}) => (
                <div key={q.id} className="rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2 text-xs">
                  <div className="flex items-center justify-between mb-0.5">
                    <span className={`font-bold ${q.priority === "high" ? "text-[var(--accent-red)]" : q.priority === "critical" ? "text-red-500" : "text-[var(--accent-amber)]"}`}>
                      {q.priority}
                    </span>
                    <span className="text-[var(--text-secondary)]">{q.source_agent}</span>
                  </div>
                  <p className="text-[var(--text-secondary)] line-clamp-2">{q.description}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="py-3 text-center text-xs text-[var(--text-secondary)]">未処理のエスカレーションなし</p>
          )}
        </div>

        {/* brain_handoff */}
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2 mb-3">
            <ArrowDownLeft className="h-4 w-4 text-[var(--accent-blue)]" />
            <h2 className="text-sm font-semibold">ハンドオフ</h2>
            <span className="ml-auto text-[10px] text-[var(--text-secondary)]">{handoffs.length}件</span>
          </div>
          {handoffs.length > 0 ? (
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {handoffs.map((h: {id: number; direction: string; title: string; status: string; source_agent: string; created_at: string}) => (
                <div key={h.id} className="rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="truncate">{h.title}</span>
                    <span className={`flex-shrink-0 ml-1 rounded-full px-1.5 py-0.5 text-[10px] ${
                      h.status === "pending" ? "bg-[var(--accent-amber)]/10 text-[var(--accent-amber)]" :
                      h.status === "completed" ? "bg-[var(--accent-green)]/10 text-[var(--accent-green)]" :
                      "bg-[var(--text-secondary)]/10 text-[var(--text-secondary)]"
                    }`}>{h.status}</span>
                  </div>
                  <div className="flex items-center justify-between text-[10px] text-[var(--text-secondary)] mt-0.5">
                    <span>{h.direction === "beta_to_alpha" ? "β→α" : "α→β"} / {h.source_agent}</span>
                    <span>{h.created_at ? new Date(h.created_at).toLocaleString("ja-JP") : ""}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="py-3 text-center text-xs text-[var(--text-secondary)]">ハンドオフなし</p>
          )}
        </div>
      </div>

      {/* 相互評価 */}
      {crossEvals.length > 0 && (
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2 mb-3">
            <Scale className="h-4 w-4 text-[var(--accent-purple)]" />
            <h2 className="text-sm font-semibold">相互評価（β→α検証）</h2>
            <span className="ml-auto text-[10px] text-[var(--text-secondary)]">{crossEvals.length}件</span>
          </div>
          <div className="space-y-2">
            {crossEvals.map((ev: {id: number; target_type: string; target_id: string; score: number | null; evaluation: string; recommendations: {verdict?: string; accuracy?: string; error_improvement?: number; quality_improvement?: number}; created_at: string}) => {
              const s = ev.score ?? 0;
              const color = s >= 0.7 ? "text-[var(--accent-green)]" : s >= 0.4 ? "text-[var(--accent-amber)]" : "text-[var(--accent-red)]";
              const bg = s >= 0.7 ? "bg-[var(--accent-green)]/10" : s >= 0.4 ? "bg-[var(--accent-amber)]/10" : "bg-[var(--accent-red)]/10";
              const r = ev.recommendations || {};
              const label = r.verdict || r.accuracy || "";
              return (
                <div key={ev.id} className="rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2 text-xs">
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[var(--text-secondary)]">{ev.target_type}#{ev.target_id}</span>
                      {label && <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${bg} ${color}`}>{label}</span>}
                    </div>
                    <span className={`font-bold ${color}`}>{(s * 100).toFixed(0)}%</span>
                  </div>
                  <p className="text-[var(--text-secondary)]">{ev.evaluation}</p>
                  <p className="text-[10px] text-[var(--text-secondary)] mt-0.5">
                    {ev.created_at ? new Date(ev.created_at).toLocaleString("ja-JP") : ""}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* セッション記憶 */}
      <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
        <div className="flex items-center gap-2 mb-3">
          <Brain className="h-4 w-4 text-[var(--accent-amber)]" />
          <h2 className="text-sm font-semibold">セッション記憶</h2>
          <span className="ml-auto text-[10px] text-[var(--text-secondary)]">{sessions.length}件</span>
        </div>
        {sessions.length > 0 ? (
          <div className="space-y-2">
            {sessions.map((s, i: number) => (
              <details key={s.id} open={i === 0}>
                <summary className="cursor-pointer rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2 text-xs">
                  <span className="font-mono text-[var(--accent-purple)]">{s.session_id}</span>
                  <span className="ml-2 text-[var(--text-secondary)]">
                    {s.started_at ? new Date(s.started_at).toLocaleString("ja-JP") : ""}
                  </span>
                  {s.daichi_interactions > 0 && (
                    <span className="ml-1 text-[var(--accent-green)]">対話{s.daichi_interactions}</span>
                  )}
                </summary>
                <div className="px-3 pb-2 text-xs space-y-1 mt-1">
                  {s.summary && <p>{s.summary}</p>}
                  {s.key_decisions && s.key_decisions.length > 0 && (
                    <div>
                      <span className="text-[var(--text-secondary)]">判断: </span>
                      {s.key_decisions.map((d: string, j: number) => <span key={j} className="mr-1">• {d}</span>)}
                    </div>
                  )}
                  {s.unresolved_issues && s.unresolved_issues.length > 0 && (
                    <div>
                      <span className="text-[var(--accent-amber)]">未解決: </span>
                      {s.unresolved_issues.map((u: string, j: number) => <span key={j} className="mr-1">• {u}</span>)}
                    </div>
                  )}
                </div>
              </details>
            ))}
          </div>
        ) : (
          <p className="py-4 text-center text-sm text-[var(--text-secondary)]">セッション記憶はまだありません</p>
        )}
      </div>

      {/* Daichi対話ログ */}
      {dialogues.length > 0 && (
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2 mb-3">
            <MessageCircle className="h-4 w-4 text-[var(--accent-purple)]" />
            <h2 className="text-sm font-semibold">Daichi対話ログ</h2>
            <span className="ml-auto text-[10px] text-[var(--text-secondary)]">{dialogues.length}件</span>
          </div>
          <div className="space-y-2">
            {dialogues.map((d: {id: number; channel: string; daichi_message: string; extracted_philosophy: {content?: string; importance?: number} | null; created_at: string}) => (
              <div key={d.id} className="rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2 text-xs">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[var(--accent-purple)] font-medium">{d.channel}</span>
                  <span className="text-[var(--text-secondary)]">{d.created_at ? new Date(d.created_at).toLocaleString("ja-JP") : ""}</span>
                </div>
                <p className="line-clamp-2">{d.daichi_message}</p>
                {d.extracted_philosophy && d.extracted_philosophy.content && (
                  <div className="mt-1 flex items-center gap-1 text-[10px]">
                    <span className="text-[var(--accent-green)]">抽出:</span>
                    <span className="text-[var(--text-secondary)]">{d.extracted_philosophy.content}</span>
                    {d.extracted_philosophy.importance != null && (
                      <span className={`ml-auto ${(d.extracted_philosophy.importance ?? 0) >= 0.7 ? "text-[var(--accent-green)]" : "text-[var(--text-secondary)]"}`}>
                        {((d.extracted_philosophy.importance ?? 0) * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* persona_memory統計 */}
      {personaStats && (
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2 mb-3">
            <Database className="h-4 w-4 text-[var(--accent-blue)]" />
            <h2 className="text-sm font-semibold">人格記憶（persona_memory）</h2>
            <span className="ml-auto text-[10px] text-[var(--text-secondary)]">{personaStats.total}件</span>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {personaStats.categories.map((c) => {
              const pct = personaStats.total > 0 ? Math.round((c.count / personaStats.total) * 100) : 0;
              const catLabels: Record<string, string> = {
                philosophy: "哲学・価値観",
                conversation: "会話パターン",
                approval_pattern: "承認パターン",
                judgment: "判断基準",
                preference: "好み・嗜好",
              };
              return (
                <div key={c.category} className="rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2">
                  <p className="text-xs font-medium">{catLabels[c.category] || c.category}</p>
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-lg font-bold">{c.count}</span>
                    <span className="text-[10px] text-[var(--text-secondary)]">{pct}%</span>
                  </div>
                  <div className="mt-1 h-1 w-full rounded-full bg-[var(--bg-secondary)]">
                    <div className="h-1 rounded-full bg-[var(--accent-purple)] transition-all" style={{ width: `${pct}%` }} />
                  </div>
                  <p className="text-[10px] text-[var(--text-secondary)] mt-0.5">ベクトル化: {c.embedded}/{c.count}</p>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
