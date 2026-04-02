"use client";

import { useEffect, useState } from "react";
import { Bot, Wifi, WifiOff, Activity, Monitor, Power, XCircle, CheckCircle2, Loader2, Clock, AlertCircle, ScrollText, Filter, Brain } from "lucide-react";
import NodeStatusPanel from "@/components/NodeStatusPanel";
import { apiFetch } from "@/lib/api";

interface NodeInfo {
  name: string;
  status: "online" | "offline" | "busy";
  cpu: number;
  memory: number;
  model: string;
  browser_layer: boolean;
}

interface AgentOpsData {
  nodes: NodeInfo[];
  nats_connected: boolean;
  loop_guard_active: boolean;
  emergency_kills_today: number;
  total_steps_today: number;
  daily_budget_used: number;
  active_goals: {
    id: string;
    description: string;
    node: string;
    step: number;
    max_steps: number;
  }[];
}

import { NODE_MODELS } from "@/lib/constants";

function TaskOutputPreview({ data }: { data: unknown }) {
  let preview = "";
  try {
    const od = typeof data === "string" ? JSON.parse(data) : data;
    const raw = od as Record<string, unknown>;
    preview = String(raw.text || raw.content || raw.message || JSON.stringify(raw)).slice(0, 150);
  } catch {
    preview = String(data).slice(0, 150);
  }
  if (!preview) return null;
  return <p className="mt-1 text-xs text-[var(--text-secondary)] line-clamp-2">{preview}</p>;
}

interface EventLogEntry {
  id: number;
  event_type: string;
  category: string;
  severity: string;
  source_node: string;
  goal_id: string | null;
  task_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

const SEVERITY_COLORS: Record<string, string> = {
  info: "text-[var(--text-secondary)]",
  warning: "text-yellow-400",
  error: "text-[var(--accent-red)]",
  critical: "text-red-500 font-bold",
};

const CATEGORY_OPTIONS = ["", "llm", "task", "goal", "sns", "system", "node"];

export default function AgentOpsPage() {
  const [data, setData] = useState<AgentOpsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [charlieShuttingDown, setCharlieShuttingDown] = useState(false);
  const [events, setEvents] = useState<EventLogEntry[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [brainPhases, setBrainPhases] = useState<Record<string, any> | null>(null);
  const [eventCategory, setEventCategory] = useState("");
  const [goalDetail, setGoalDetail] = useState<{
    goal: Record<string, unknown>;
    tasks: Record<string, unknown>[];
    summary: Record<string, number>;
  } | null>(null);
  const [goalLoading, setGoalLoading] = useState(false);
  const [recentlyCompletedGoals, setRecentlyCompletedGoals] = useState<{ id: string; description: string; completed_at: string }[]>([]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const catParam = eventCategory ? `&category=${eventCategory}` : "";
        const [nodesRes, opsRes, eventsRes, brainRes] = await Promise.all([
          apiFetch("/api/nodes/status"),
          apiFetch("/api/agent-ops/status").catch(() => null),
          apiFetch(`/api/events?limit=30${catParam}`).catch(() => null),
          apiFetch("/api/brain-alpha/latest-report").catch(() => null),
        ]);
        const nodesJson = nodesRes.ok ? await nodesRes.json() : null;
        const opsJson = opsRes && opsRes.ok ? await opsRes.json() : null;

        const nodeList: NodeInfo[] = ["alpha", "bravo", "charlie", "delta"].map((name) => {
          const nodeData = nodesJson?.nodes?.[name];
          const info = NODE_MODELS[name] || { model: "unknown", browser_layer: false };
          return {
            name: name.toUpperCase(),
            status: nodeData?.status === "alive" ? "online" : "offline",
            cpu: nodeData?.cpu_percent ?? 0,
            memory: nodeData?.memory_percent ?? 0,
            model: info.model,
            browser_layer: info.browser_layer,
          };
        });

        const natsConnected = nodesJson?.nodes?.bravo?.status === "alive" ||
                              nodesJson?.nodes?.charlie?.status === "alive" ||
                              nodesJson?.nodes?.delta?.status === "alive";

        // CHARLIEがオフラインになったらシャットダウン中状態をリセット
        const charlieStatus = nodeList.find((n) => n.name === "CHARLIE");
        if (charlieStatus?.status === "offline") {
          setCharlieShuttingDown(false);
        }

        // Brain-αレポート
        if (brainRes && brainRes.ok) {
          const brJson = await brainRes.json();
          if (brJson.report?.phases) setBrainPhases(brJson.report.phases);
        }

        // イベントログ
        if (eventsRes && eventsRes.ok) {
          const evJson = await eventsRes.json();
          setEvents(evJson.events ?? []);
        }

        if (opsJson?.recently_completed_goals) {
          setRecentlyCompletedGoals(opsJson.recently_completed_goals);
        }

        setData({
          nodes: nodeList,
          nats_connected: opsJson?.nats_connected ?? natsConnected,
          loop_guard_active: opsJson?.loop_guard_active ?? true,
          emergency_kills_today: opsJson?.emergency_kills_today ?? 0,
          total_steps_today: opsJson?.total_steps_today ?? 0,
          daily_budget_used: opsJson?.daily_budget_used ?? 0,
          active_goals: opsJson?.active_goals ?? [],
        });
      } catch {
        setData({
          nodes: [],
          nats_connected: false,
          loop_guard_active: false,
          emergency_kills_today: 0,
          total_steps_today: 0,
          daily_budget_used: 0,
          active_goals: [],
        });
      } finally {
        setLoading(false);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [eventCategory]);

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--accent-purple)] border-t-transparent" />
      </div>
    );
  }

  const openGoalDetail = async (goalIdShort: string) => {
    setGoalLoading(true);
    try {
      // goal_idの先頭12文字しかないので、DBから完全なIDを検索
      const res = await apiFetch(`/api/goals/${goalIdShort}`);
      if (res.ok) {
        const detail = await res.json();
        setGoalDetail(detail);
      }
    } catch {
      // ignore
    } finally {
      setGoalLoading(false);
    }
  };

  const taskStatusIcon = (status: string) => {
    switch (status) {
      case "success": case "completed": case "complete":
        return <CheckCircle2 className="h-4 w-4 text-[var(--accent-green)]" />;
      case "running":
        return <Loader2 className="h-4 w-4 text-[var(--accent-blue)] animate-spin" />;
      case "pending": case "queued":
        return <Clock className="h-4 w-4 text-[var(--text-secondary)]" />;
      case "failure": case "failed":
        return <AlertCircle className="h-4 w-4 text-[var(--accent-red)]" />;
      default:
        return <Clock className="h-4 w-4 text-[var(--text-secondary)]" />;
    }
  };

  const TASK_TYPE_JP: Record<string, string> = {
    content: "コンテンツ生成", research: "調査", analysis: "分析",
    pricing: "価格設定", coding: "コード作成", drafting: "下書き",
    browser_action: "ブラウザ操作", strategy: "戦略分析",
    proposal: "提案", approval_request: "承認リクエスト",
  };

  const d = data!;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Bot className="h-6 w-6 text-[var(--accent-purple)]" />
        <h1 className="text-2xl font-bold">Agent Operations</h1>
      </div>

      {/* System Status */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
            {d.nats_connected ? <Wifi className="h-4 w-4 text-[var(--accent-green)]" /> : <WifiOff className="h-4 w-4 text-[var(--accent-red)]" />}
            NATS
          </div>
          <p className={`mt-1 text-lg font-bold ${d.nats_connected ? "text-[var(--accent-green)]" : "text-[var(--accent-red)]"}`}>
            {d.nats_connected ? "接続中" : "切断"}
          </p>
        </div>
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
            <Activity className="h-4 w-4" />
            LoopGuard
          </div>
          <p className={`mt-1 text-lg font-bold ${d.loop_guard_active ? "text-[var(--accent-green)]" : "text-[var(--accent-red)]"}`}>
            {d.loop_guard_active ? "有効" : "無効"}
          </p>
        </div>
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <p className="text-sm text-[var(--text-secondary)]">今日のステップ</p>
          <p className="mt-1 text-lg font-bold">{d.total_steps_today} / 100</p>
          <div className="mt-1 h-1.5 w-full rounded-full bg-[var(--bg-primary)]">
            <div
              className={`h-1.5 rounded-full transition-all ${d.total_steps_today > 80 ? "bg-[var(--accent-red)]" : "bg-[var(--accent-blue)]"}`}
              style={{ width: `${Math.min((d.total_steps_today / 100) * 100, 100)}%` }}
            />
          </div>
        </div>
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <p className="text-sm text-[var(--text-secondary)]">日次予算</p>
          <p className="mt-1 text-lg font-bold">{d.daily_budget_used}%</p>
          <div className="mt-1 h-1.5 w-full rounded-full bg-[var(--bg-primary)]">
            <div
              className={`h-1.5 rounded-full transition-all ${d.daily_budget_used > 80 ? "bg-[var(--accent-red)]" : "bg-[var(--accent-green)]"}`}
              style={{ width: `${d.daily_budget_used}%` }}
            />
          </div>
        </div>
      </div>

      {/* CHARLIE操作 */}
      {(() => {
        const charlieNode = d.nodes.find((n) => n.name === "CHARLIE");
        const isOnline = charlieNode?.status === "online";
        return (
          <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
            <div className="mb-3 flex items-center gap-2">
              <Monitor className="h-5 w-5 text-[var(--accent-purple)]" />
              <h2 className="text-lg font-semibold">CHARLIE操作</h2>
            </div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span
                  className={`inline-block h-2.5 w-2.5 rounded-full ${
                    charlieShuttingDown
                      ? "animate-pulse bg-[var(--accent-amber)]"
                      : isOnline
                        ? "bg-[var(--accent-green)]"
                        : "bg-[var(--accent-amber)]"
                  }`}
                />
                <span className="text-sm">
                  {charlieShuttingDown
                    ? "切り替え中..."
                    : isOnline
                      ? "オンライン（Ubuntu）"
                      : "オフライン（Win11使用中）"}
                </span>
              </div>
              {charlieShuttingDown ? (
                <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--accent-amber)] border-t-transparent" />
                  切り替え中...
                </div>
              ) : isOnline ? (
                <button
                  className="flex items-center gap-1.5 rounded-md border border-[var(--accent-amber)] px-3 py-1.5 text-sm font-medium text-[var(--accent-amber)] transition-colors hover:bg-[var(--accent-amber)]/10"
                  onClick={async () => {
                    const ok = window.confirm(
                      "CHARLIEをシャットダウンしてWin11に切り替えますか？\nエージェント処理が中断されます。"
                    );
                    if (!ok) return;
                    setCharlieShuttingDown(true);
                    try {
                      await apiFetch("/api/charlie/shutdown", { method: "POST" });
                    } catch {
                      // エラー時もUI上は切り替え中として表示し、次のポーリングで状態が更新される
                    }
                  }}
                >
                  <Power className="h-4 w-4" />
                  Win11に切り替え
                </button>
              ) : null}
            </div>
          </div>
        );
      })()}

      {/* Nodes */}
      {d.nodes.length > 0 && <NodeStatusPanel nodes={d.nodes} />}

      {/* Brain-α 精査Phase */}
      {brainPhases && (
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2 mb-3">
            <Brain className="h-5 w-5 text-[var(--accent-purple)]" />
            <h2 className="text-lg font-semibold">Brain-&alpha; 精査サイクル</h2>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              { key: "1_session_restore", label: "1.セッション", icon: "🧠" },
              { key: "2_daichi_thoughts", label: "2.Daichi思考", icon: "💭" },
              { key: "3_intel_review", label: "3.情報収集", icon: "📡" },
              { key: "4_artifacts", label: "4.成果物", icon: "📦" },
              { key: "5_quality_trend", label: "5.品質推移", icon: "📊" },
              { key: "6_errors", label: "6.エラー", icon: "⚠️" },
              { key: "7_revenue", label: "7.収益", icon: "💰" },
              { key: "8_trace_queue", label: "8.キュー", icon: "📋" },
            ].map((phase) => {
              const data = brainPhases[phase.key];
              const hasError = data?.error;
              const hasData = data && !hasError;
              return (
                <div key={phase.key} className={`rounded-md border px-3 py-2 text-xs ${
                  hasError ? "border-[var(--accent-red)]/30 bg-[var(--accent-red)]/5" :
                  hasData ? "border-[var(--accent-green)]/30 bg-[var(--accent-green)]/5" :
                  "border-[var(--border-color)] bg-[var(--bg-primary)]"
                }`}>
                  <div className="flex items-center gap-1">
                    <span>{phase.icon}</span>
                    <span className="font-medium">{phase.label}</span>
                  </div>
                  <span className={`text-[10px] ${hasError ? "text-[var(--accent-red)]" : hasData ? "text-[var(--accent-green)]" : "text-[var(--text-secondary)]"}`}>
                    {hasError ? "エラー" : hasData ? "完了" : "未実行"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Active Goals */}
      <div>
        <h2 className="mb-3 text-lg font-semibold">稼働中のゴール</h2>
        <div className="space-y-2">
          {d.active_goals.map((goal) => (
            <div
              key={goal.id}
              onClick={() => openGoalDetail(goal.id)}
              className="cursor-pointer rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] px-4 py-3 hover:border-[var(--accent-purple)]/50 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium">{goal.description}</p>
                  <p className="text-xs text-[var(--text-secondary)]">
                    {goal.id} &middot; ノード: {goal.node}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-medium">
                    Step {goal.step}/{goal.max_steps}
                  </p>
                  <div className="mt-1 h-1.5 w-24 rounded-full bg-[var(--bg-primary)]">
                    <div
                      className="h-1.5 rounded-full bg-[var(--accent-purple)] transition-all"
                      style={{ width: `${(goal.step / goal.max_steps) * 100}%` }}
                    />
                  </div>
                </div>
              </div>
            </div>
          ))}
          {d.active_goals.length === 0 && (
            <p className="py-8 text-center text-[var(--text-secondary)]">稼働中のゴールはありません</p>
          )}
        </div>
      </div>

      {/* Recently Completed Goals */}
      {recentlyCompletedGoals.length > 0 && (
        <div>
          <h2 className="mb-3 text-lg font-semibold">最近完了したゴール</h2>
          <div className="space-y-2">
            {recentlyCompletedGoals.map((goal) => (
              <div
                key={goal.id}
                onClick={() => openGoalDetail(goal.id)}
                className="cursor-pointer rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] px-4 py-3 hover:border-[var(--accent-green)]/50 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <div className="min-w-0">
                    <p className="font-medium truncate">{goal.description}</p>
                    <p className="text-xs text-[var(--text-secondary)]">
                      {goal.id} &middot; {goal.completed_at ? new Date(goal.completed_at).toLocaleString("ja-JP") : ""}
                    </p>
                  </div>
                  <span className="flex-shrink-0 rounded-full bg-[var(--accent-green)]/10 px-2.5 py-0.5 text-xs font-medium text-[var(--accent-green)]">
                    完了
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Event Log Stream */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ScrollText className="h-5 w-5 text-[var(--accent-purple)]" />
            <h2 className="text-lg font-semibold">イベントログ</h2>
          </div>
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-[var(--text-secondary)]" />
            <select
              value={eventCategory}
              onChange={(e) => setEventCategory(e.target.value)}
              className="rounded-md border border-[var(--border-color)] bg-[var(--bg-card)] px-2 py-1 text-sm text-[var(--text-primary)]"
            >
              <option value="">全て</option>
              {CATEGORY_OPTIONS.filter(Boolean).map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="space-y-1 max-h-[400px] overflow-y-auto rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-3">
          {events.length > 0 ? events.map((ev) => (
            <div key={ev.id} className="flex items-start gap-2 border-b border-[var(--border-color)] py-1.5 last:border-b-0 text-xs">
              <span className="shrink-0 text-[var(--text-secondary)] w-14">
                {ev.created_at ? new Date(ev.created_at).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""}
              </span>
              <span className={`shrink-0 w-6 text-center font-mono ${SEVERITY_COLORS[ev.severity] || ""}`}>
                {ev.severity === "critical" ? "!!" : ev.severity === "error" ? "E" : ev.severity === "warning" ? "W" : "·"}
              </span>
              <span className="shrink-0 w-16 text-[var(--accent-purple)] font-medium truncate">{ev.source_node || "-"}</span>
              <span className="font-medium text-[var(--text-primary)]">{ev.event_type}</span>
              <span className="text-[var(--text-secondary)] truncate flex-1">
                {(() => {
                  const p = ev.payload || {};
                  const keys = Object.keys(p).slice(0, 3);
                  return keys.map((k) => `${k}=${String(p[k]).slice(0, 30)}`).join(" ");
                })()}
              </span>
            </div>
          )) : (
            <p className="py-4 text-center text-sm text-[var(--text-secondary)]">イベントログはまだありません</p>
          )}
        </div>
      </div>

      {/* ゴール詳細モーダル */}
      {goalDetail && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setGoalDetail(null)}
        >
          <div
            className="w-full max-w-lg max-h-[80vh] overflow-y-auto rounded-xl border border-[var(--border-color)] bg-[var(--bg-card)] p-6 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-lg">ゴール詳細</h3>
              <button onClick={() => setGoalDetail(null)} className="text-[var(--text-secondary)] hover:text-white">
                <XCircle className="h-5 w-5" />
              </button>
            </div>

            <div>
              <p className="text-sm text-[var(--text-secondary)]">ゴール</p>
              <p className="font-medium">{String(goalDetail.goal.raw_goal || goalDetail.goal.parsed_objective || "")}</p>
            </div>

            <div className="flex gap-4 text-sm">
              <div>
                <span className="text-[var(--text-secondary)]">ステータス: </span>
                <span className="font-medium">{String(goalDetail.goal.status)}</span>
              </div>
              <div>
                <span className="text-[var(--text-secondary)]">進捗: </span>
                <span className="font-medium">
                  {goalDetail.summary.completed}/{goalDetail.summary.total} 完了
                </span>
              </div>
            </div>

            {goalDetail.summary.total > 0 && (
              <div className="h-2 w-full rounded-full bg-[var(--bg-primary)]">
                <div
                  className="h-2 rounded-full bg-[var(--accent-purple)] transition-all"
                  style={{
                    width: `${(goalDetail.summary.completed / goalDetail.summary.total) * 100}%`,
                  }}
                />
              </div>
            )}

            <div className="space-y-2">
              <p className="text-sm font-semibold">タスク一覧</p>
              {goalDetail.tasks.map((task) => (
                <div
                  key={String(task.id)}
                  className="flex items-start gap-3 rounded-lg border border-[var(--border-color)] bg-[var(--bg-primary)] p-3"
                >
                  <div className="mt-0.5">{taskStatusIcon(String(task.status))}</div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">
                      {TASK_TYPE_JP[String(task.type)] || String(task.type)}
                    </p>
                    <p className="text-xs text-[var(--text-secondary)]">
                      {String(task.assigned_node || "-")}
                      {task.model_used ? ` · ${task.model_used}` : ""}
                      {task.cost_jpy ? ` · ¥${Number(task.cost_jpy).toFixed(2)}` : ""}
                    </p>
                    {/* 完了タスクの出力プレビュー */}
                    {Boolean(task.output_data) && ["success", "completed", "complete"].includes(String(task.status)) && (
                      <TaskOutputPreview data={task.output_data} />
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {goalLoading && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--accent-purple)] border-t-transparent" />
        </div>
      )}
    </div>
  );
}
