"use client";

import { useEffect, useState } from "react";
import { Activity, DollarSign, CheckCircle, AlertTriangle, CircleDollarSign, Send, Zap, Monitor, Brain, Wrench } from "lucide-react";
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

interface RecentArtifact {
  task_id: string;
  type: string;
  status: string;
  assigned_node: string;
  model_used: string;
  cost_jpy: number;
  output_preview: string;
  completed_at: string;
}

interface DashboardData {
  nodes: NodeInfo[];
  active_tasks: number;
  running_tasks: number;
  pending_tasks: number;
  completed_tasks_today: number;
  today_revenue: number;
  pending_approvals: number;
  daily_cost: number;
  daily_budget: number;
  monthly_cost: number;
  monthly_budget: number;
  recent_proposals: {
    id: string;
    title: string;
    layer: string;
    status: string;
    created_at: string;
  }[];
  recent_artifacts: RecentArtifact[];
}

const NODE_MODELS: Record<string, { model: string; browser_layer: boolean }> = {
  alpha: { model: "推論なし（Brain-α専用）", browser_layer: false },
  bravo: { model: "Nemotron 9B JP + Qwen3.5-9B", browser_layer: true },
  charlie: { model: "Nemotron 9B JP + Qwen3.5-9B", browser_layer: false },
  delta: { model: "Qwen3.5-4B", browser_layer: false },
};

interface NodeStateInfo {
  node_name: string;
  state: string;
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nodeStates, setNodeStates] = useState<NodeStateInfo[]>([]);
  const [charlieSwitching, setCharlieSwitching] = useState(false);
  const [brainReport, setBrainReport] = useState<{summary: string; recommended_actions: string[]; warnings: string[]} | null>(null);
  const [pendingEscalations, setPendingEscalations] = useState(0);
  const [healStats, setHealStats] = useState<{total_24h: number; success_rate_24h: number} | null>(null);
  const [quickGoal, setQuickGoal] = useState("");
  const [goalSending, setGoalSending] = useState(false);
  const [goalSent, setGoalSent] = useState(false);

  useEffect(() => {
    const fetchDashboard = async () => {
      try {
        const [dashRes, nodesRes, budgetRes, revenueRes, nodeStateRes, brainRes, queueRes, healRes] = await Promise.all([
          apiFetch("/api/dashboard"),
          apiFetch("/api/nodes/status"),
          apiFetch("/api/budget/status").catch(() => null),
          apiFetch("/api/revenue").catch(() => null),
          apiFetch("/api/nodes/state").catch(() => null),
          apiFetch("/api/brain-alpha/latest-report").catch(() => null),
          apiFetch("/api/brain-alpha/queue?status=pending").catch(() => null),
          apiFetch("/api/self-healing/stats").catch(() => null),
        ]);

        if (!dashRes.ok) throw new Error("Dashboard API error");

        const dashJson = await dashRes.json();
        const nodesJson = nodesRes.ok ? await nodesRes.json() : null;
        const budgetJson = budgetRes && budgetRes.ok ? await budgetRes.json() : null;
        const revenueJson = revenueRes && revenueRes.ok ? await revenueRes.json() : null;

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

        const mapped: DashboardData = {
          nodes: nodeList,
          active_tasks: (dashJson.running_tasks ?? 0) + (dashJson.pending_tasks ?? 0),
          running_tasks: dashJson.running_tasks ?? 0,
          pending_tasks: dashJson.pending_tasks ?? 0,
          completed_tasks_today: dashJson.completed_tasks_today ?? 0,
          today_revenue: revenueJson?.today_revenue ?? dashJson.today_revenue ?? 0,
          pending_approvals: dashJson.pending_approvals ?? 0,
          daily_cost: budgetJson?.daily_spent_jpy ?? 0,
          daily_budget: budgetJson?.daily_budget_jpy ?? 80,
          monthly_cost: budgetJson?.monthly_spent_jpy ?? 0,
          monthly_budget: budgetJson?.monthly_budget_jpy ?? 1500,
          recent_proposals: dashJson.recent_proposals ?? [],
          recent_artifacts: dashJson.recent_artifacts ?? [],
        };
        setData(mapped);
        setError(null);

        if (nodeStateRes && nodeStateRes.ok) {
          const nsJson = await nodeStateRes.json();
          setNodeStates(nsJson.nodes || []);
        }
        if (brainRes && brainRes.ok) {
          const brJson = await brainRes.json();
          if (brJson.report) setBrainReport(brJson.report);
        }
        if (queueRes && queueRes.ok) {
          const qJson = await queueRes.json();
          setPendingEscalations(qJson.queue?.length || 0);
        }
        if (healRes && healRes.ok) {
          const hJson = await healRes.json();
          setHealStats({total_24h: hJson.total_24h || 0, success_rate_24h: hJson.success_rate_24h || 0});
        }
      } catch {
        setError("API接続エラー");
        if (!data) {
          setData({
            nodes: [],
            active_tasks: 0,
            running_tasks: 0,
            pending_tasks: 0,
            completed_tasks_today: 0,
            today_revenue: 0,
            pending_approvals: 0,
            daily_cost: 0,
            daily_budget: 80,
            monthly_cost: 0,
            monthly_budget: 1500,
            recent_proposals: [],
            recent_artifacts: [],
          });
        }
      } finally {
        setLoading(false);
      }
    };
    fetchDashboard();
    const interval = setInterval(fetchDashboard, 10000);
    return () => clearInterval(interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sendQuickGoal = async () => {
    const text = quickGoal.trim();
    if (!text || goalSending) return;
    setGoalSending(true);
    try {
      const res = await apiFetch("/api/chat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: "default" }),
      });
      if (res.ok) {
        setQuickGoal("");
        setGoalSent(true);
        setTimeout(() => setGoalSent(false), 3000);
      }
    } catch {
      // ignore
    } finally {
      setGoalSending(false);
    }
  };

  const charlieState = nodeStates.find((n) => n.node_name === "charlie");
  const isCharlieWin11 = charlieState?.state === "charlie_win11";

  const toggleCharlie = async () => {
    setCharlieSwitching(true);
    try {
      const newMode = isCharlieWin11 ? "ubuntu" : "win11";
      await apiFetch("/api/nodes/charlie/mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: newMode }),
      });
    } catch {
      // ignore
    } finally {
      setCharlieSwitching(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--accent-purple)] border-t-transparent" />
      </div>
    );
  }

  const d = data!;
  const dailyPct = d.daily_budget > 0 ? Math.min((d.daily_cost / d.daily_budget) * 100, 100) : 0;
  const monthlyPct = d.monthly_budget > 0 ? Math.min((d.monthly_cost / d.monthly_budget) * 100, 100) : 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">ダッシュボード</h1>
        {error && (
          <span className="flex items-center gap-1 rounded-full bg-[var(--accent-amber)]/10 px-3 py-1 text-xs text-[var(--accent-amber)]">
            <AlertTriangle className="h-3 w-3" />
            {error}
          </span>
        )}
      </div>

      {/* Quick Goal Input */}
      <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
        <div className="flex items-center gap-2 mb-3">
          <Zap className="h-5 w-5 text-[var(--accent-purple)]" />
          <h2 className="text-sm font-semibold">クイックゴール入力</h2>
          {goalSent && (
            <span className="ml-auto text-xs text-[var(--accent-green)]">送信しました</span>
          )}
        </div>
        <div className="flex gap-2">
          <input
            type="text"
            value={quickGoal}
            onChange={(e) => setQuickGoal(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendQuickGoal()}
            placeholder="ゴールを入力... (例: 今月中に入口商品を1本出したい)"
            className="flex-1 rounded-lg border border-[var(--border-color)] bg-[var(--bg-primary)] px-4 py-2 text-sm text-white placeholder-[var(--text-secondary)] outline-none focus:border-[var(--accent-purple)] transition-colors"
            disabled={goalSending}
          />
          <button
            onClick={sendQuickGoal}
            disabled={goalSending || !quickGoal.trim()}
            className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--accent-purple)] text-white hover:bg-[var(--accent-purple)]/80 transition-colors disabled:opacity-50"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-[var(--accent-blue)]" />
            <p className="text-xs text-[var(--text-secondary)]">稼働タスク</p>
          </div>
          <p className="mt-1 text-2xl font-bold">{d.active_tasks}</p>
          <p className="text-xs text-[var(--text-secondary)]">
            {d.running_tasks > 0 && <span className="text-[var(--accent-blue)]">実行中{d.running_tasks}</span>}
            {d.running_tasks > 0 && d.pending_tasks > 0 && " / "}
            {d.pending_tasks > 0 && <>待機{d.pending_tasks}</>}
            {d.running_tasks === 0 && d.pending_tasks === 0 && "待機なし"}
            {" "}/ 完了{d.completed_tasks_today}
          </p>
        </div>
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2">
            <DollarSign className="h-4 w-4 text-[var(--accent-green)]" />
            <p className="text-xs text-[var(--text-secondary)]">今日の収益</p>
          </div>
          <p className="mt-1 text-2xl font-bold">&yen;{d.today_revenue.toLocaleString()}</p>
        </div>
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2">
            <CheckCircle className="h-4 w-4 text-[var(--accent-amber)]" />
            <p className="text-xs text-[var(--text-secondary)]">承認待ち</p>
          </div>
          <p className="mt-1 text-2xl font-bold">{d.pending_approvals}</p>
        </div>
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2">
            <CircleDollarSign className="h-4 w-4 text-[var(--accent-purple)]" />
            <p className="text-xs text-[var(--text-secondary)]">APIコスト</p>
          </div>
          <p className="mt-1 text-lg font-bold">&yen;{d.daily_cost < 10 ? d.daily_cost.toFixed(1) : d.daily_cost.toFixed(0)}</p>
          <div className="mt-1 h-1.5 w-full rounded-full bg-[var(--bg-primary)]">
            <div
              className={`h-1.5 rounded-full transition-all ${dailyPct > 80 ? "bg-[var(--accent-red)]" : "bg-[var(--accent-green)]"}`}
              style={{ width: `${dailyPct}%` }}
            />
          </div>
          <p className="mt-0.5 text-[10px] text-[var(--text-secondary)]">日次 &yen;{d.daily_budget} / 月次 &yen;{d.monthly_cost.toFixed(0)}/{d.monthly_budget}</p>
        </div>
      </div>

      {/* Brain-α 精査サマリー */}
      {brainReport && (
        <a href="/brain-alpha" className="block rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4 hover:border-[var(--accent-purple)]/50 transition-colors">
          <div className="flex items-center gap-2 mb-2">
            <Brain className="h-4 w-4 text-[var(--accent-purple)]" />
            <h2 className="text-sm font-semibold">Brain-&alpha; 精査</h2>
            {pendingEscalations > 0 && (
              <span className="rounded-full bg-[var(--accent-red)]/20 px-2 py-0.5 text-[10px] text-[var(--accent-red)]">
                {pendingEscalations}件未処理
              </span>
            )}
            <span className="ml-auto text-[10px] text-[var(--text-secondary)]">{brainReport.summary}</span>
          </div>
          {brainReport.warnings.length > 0 && (
            <div className="mb-2">
              {brainReport.warnings.slice(0, 2).map((w, i) => (
                <p key={i} className="text-xs text-[var(--accent-amber)] flex items-center gap-1">
                  <AlertTriangle className="h-3 w-3 flex-shrink-0" /> {w}
                </p>
              ))}
            </div>
          )}
          {brainReport.recommended_actions.length > 0 && (
            <div className="space-y-1">
              {brainReport.recommended_actions.slice(0, 3).map((a, i) => (
                <p key={i} className="text-xs text-[var(--text-secondary)]">
                  <span className="text-[var(--accent-purple)] font-bold">{i + 1}.</span> {a}
                </p>
              ))}
            </div>
          )}
        </a>
      )}

      {/* 修復ステータスカード */}
      {healStats && healStats.total_24h > 0 && (
        <a href="/node-control" className="flex items-center gap-3 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-3 hover:border-[var(--accent-blue)]/50 transition-colors">
          <Wrench className="h-5 w-5 text-[var(--accent-blue)]" />
          <div>
            <p className="text-xs text-[var(--text-secondary)]">自律修復 (24h)</p>
            <p className="text-sm font-bold">{healStats.total_24h}件 / 成功率 <span className={healStats.success_rate_24h >= 80 ? "text-[var(--accent-green)]" : "text-[var(--accent-amber)]"}>{healStats.success_rate_24h}%</span></p>
          </div>
        </a>
      )}

      {/* Node State Badges + CHARLIE Toggle */}
      {nodeStates.length > 0 && (
        <div className="flex items-center gap-3 flex-wrap">
          {nodeStates.map((ns) => {
            const color = ns.state === "healthy" ? "var(--accent-green)" : ns.state === "charlie_win11" ? "var(--accent-amber)" : "var(--accent-red)";
            const label = ns.state === "healthy" ? "稼働" : ns.state === "charlie_win11" ? "Win11" : ns.state;
            return (
              <span key={ns.node_name} className="flex items-center gap-1.5 rounded-full border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-1 text-xs">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
                <span className="font-bold">{ns.node_name.toUpperCase()}</span>
                <span style={{ color }}>{label}</span>
              </span>
            );
          })}
          <button
            onClick={toggleCharlie}
            disabled={charlieSwitching}
            className="flex items-center gap-1 rounded-full border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-1 text-xs hover:border-[var(--accent-amber)] transition-colors disabled:opacity-50"
          >
            <Monitor className="h-3 w-3" />
            {charlieSwitching ? "切替中..." : isCharlieWin11 ? "CHARLIE → Ubuntu" : "CHARLIE → Win11"}
          </button>
        </div>
      )}

      {/* Node Status */}
      {d.nodes.length > 0 ? (
        <NodeStatusPanel nodes={d.nodes} />
      ) : (
        <p className="py-4 text-center text-[var(--text-secondary)]">データなし</p>
      )}

      {/* Recent Proposals */}
      <div>
        <h2 className="mb-3 text-lg font-semibold">最近の提案</h2>
        <div className="space-y-2">
          {d.recent_proposals.map((p: Record<string, unknown>) => (
            <div
              key={String(p.proposal_id ?? p.id ?? p.title)}
              className="flex items-center justify-between rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] px-4 py-3"
            >
              <div className="min-w-0">
                <p className="font-medium truncate">{String(p.title ?? "提案")}</p>
                <p className="text-xs text-[var(--text-secondary)]">
                  {p.score ? `スコア ${p.score}点` : "-"} &middot; {p.created_at ? new Date(String(p.created_at)).toLocaleString("ja-JP") : "-"}
                </p>
              </div>
              <span
                className={`flex-shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${
                  p.status === "approved"
                    ? "bg-[var(--accent-green)]/10 text-[var(--accent-green)]"
                    : p.status === "rejected"
                    ? "bg-[var(--accent-red)]/10 text-[var(--accent-red)]"
                    : "bg-[var(--accent-amber)]/10 text-[var(--accent-amber)]"
                }`}
              >
                {String(p.status) === "approved" ? "承認済" : String(p.status) === "rejected" ? "却下" : "承認待ち"}
              </span>
            </div>
          ))}
          {d.recent_proposals.length === 0 && (
            <p className="py-8 text-center text-[var(--text-secondary)]">提案はまだありません</p>
          )}
        </div>
      </div>

      {/* Recent Artifacts */}
      {d.recent_artifacts.length > 0 && (
        <div>
          <h2 className="mb-3 text-lg font-semibold">最近の成果物</h2>
          <div className="space-y-2">
            {d.recent_artifacts.map((a) => {
              const TASK_TYPE_JP: Record<string, string> = {
                content: "コンテンツ生成", research: "調査", analysis: "分析",
                pricing: "価格設定", coding: "コード作成", drafting: "下書き",
                browser_action: "ブラウザ操作", strategy: "戦略分析",
              };
              return (
                <a
                  key={a.task_id}
                  href={`/tasks?detail=${a.task_id}`}
                  className="block rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] px-4 py-3 hover:border-[var(--accent-purple)]/50 transition-colors"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-sm">
                        {TASK_TYPE_JP[a.type] || a.type}
                      </p>
                      <p className="text-xs text-[var(--text-secondary)]">
                        {a.assigned_node} &middot; {a.completed_at ? new Date(a.completed_at).toLocaleTimeString("ja-JP") : "-"}
                        {a.cost_jpy > 0 ? ` · ¥${a.cost_jpy.toFixed(2)}` : ""}
                      </p>
                      {a.output_preview && (
                        <p className="mt-1 text-xs text-[var(--text-secondary)] line-clamp-2">
                          {a.output_preview}
                        </p>
                      )}
                    </div>
                    <span className="flex-shrink-0 rounded-full bg-[var(--accent-green)]/10 px-2.5 py-0.5 text-xs font-medium text-[var(--accent-green)]">
                      完了
                    </span>
                  </div>
                </a>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
