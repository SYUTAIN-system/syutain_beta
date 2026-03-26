"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { GitBranch, Target, Cpu, AlertTriangle, CheckCircle2, XCircle, Clock, ChevronDown } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface Goal {
  goal_id: string;
  raw_goal: string;
  status: string;
  created_at: string;
}

interface TimelineEntry {
  type: string;
  timestamp: string;
  data: Record<string, unknown>;
}

interface TimelineData {
  goal_id: string;
  goal: { raw_goal: string; status: string; created_at: string };
  timeline: TimelineEntry[];
  summary: {
    total_tasks: number;
    completed_tasks: number;
    total_events: number;
    total_llm_calls: number;
    total_cost_jpy: number;
  };
}

function TimelinePageInner() {
  const searchParams = useSearchParams();
  const goalIdParam = searchParams.get("goal_id");

  const [goals, setGoals] = useState<Goal[]>([]);
  const [selectedGoalId, setSelectedGoalId] = useState<string>(goalIdParam || "");
  const [timeline, setTimeline] = useState<TimelineData | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fetchGoals = async () => {
      try {
        const res = await apiFetch("/api/goals?limit=50");
        if (res.ok) {
          const json = await res.json();
          setGoals(json.goals ?? []);
          if (!selectedGoalId && json.goals?.length > 0) {
            setSelectedGoalId(json.goals[0].goal_id);
          }
        }
      } catch { /* ignore */ }
    };
    fetchGoals();
  }, []);

  useEffect(() => {
    if (!selectedGoalId) return;
    const fetchTimeline = async () => {
      setLoading(true);
      try {
        const res = await apiFetch(`/api/goals/${selectedGoalId}/timeline`);
        if (res.ok) {
          const json = await res.json();
          setTimeline(json);
        }
      } catch { /* ignore */ }
      setLoading(false);
    };
    fetchTimeline();
  }, [selectedGoalId]);

  const typeIcon = (type: string) => {
    switch (type) {
      case "goal_created": return <Target className="h-4 w-4 text-[var(--accent-purple)]" />;
      case "task": return <Cpu className="h-4 w-4 text-[var(--accent-blue)]" />;
      case "event": return <AlertTriangle className="h-4 w-4 text-[var(--accent-amber)]" />;
      case "llm_call": return <GitBranch className="h-4 w-4 text-[var(--accent-green)]" />;
      case "approval": return <CheckCircle2 className="h-4 w-4 text-[var(--accent-cyan)]" />;
      default: return <Clock className="h-4 w-4 text-[var(--text-secondary)]" />;
    }
  };

  const typeLabel = (type: string) => {
    const map: Record<string, string> = {
      goal_created: "ゴール作成",
      task: "タスク",
      event: "イベント",
      llm_call: "LLM呼び出し",
      approval: "承認",
    };
    return map[type] || type;
  };

  const statusColor = (status: string) => {
    if (status === "completed" || status === "approved") return "text-[var(--accent-green)]";
    if (status === "failure" || status === "rejected" || status === "cancelled") return "text-[var(--accent-red)]";
    if (status === "running" || status === "pending") return "text-[var(--accent-amber)]";
    return "text-[var(--text-secondary)]";
  };

  const formatTime = (ts: string) => {
    try {
      return new Date(ts).toLocaleString("ja-JP", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    } catch { return ts; }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <GitBranch className="h-6 w-6 text-[var(--accent-purple)]" />
        <h1 className="text-2xl font-bold">ゴール タイムライン</h1>
      </div>

      {/* ゴール選択 */}
      <div className="relative">
        <select
          value={selectedGoalId}
          onChange={(e) => setSelectedGoalId(e.target.value)}
          className="w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] px-4 py-2.5 text-sm appearance-none pr-10"
        >
          <option value="">ゴールを選択...</option>
          {goals.map((g) => (
            <option key={g.goal_id} value={g.goal_id}>
              [{g.status}] {g.raw_goal?.substring(0, 80)} ({formatTime(g.created_at)})
            </option>
          ))}
        </select>
        <ChevronDown className="absolute right-3 top-3 h-4 w-4 text-[var(--text-secondary)] pointer-events-none" />
      </div>

      {loading && (
        <div className="flex justify-center py-8">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--accent-purple)] border-t-transparent" />
        </div>
      )}

      {timeline && !loading && (
        <>
          {/* サマリー */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {[
              { label: "タスク", value: `${timeline.summary.completed_tasks}/${timeline.summary.total_tasks}` },
              { label: "イベント", value: String(timeline.summary.total_events) },
              { label: "LLM呼出", value: String(timeline.summary.total_llm_calls) },
              { label: "コスト", value: `¥${timeline.summary.total_cost_jpy.toFixed(1)}` },
              { label: "ステータス", value: timeline.goal.status },
            ].map((item) => (
              <div key={item.label} className="rounded-lg border border-[var(--border-color)]/30 bg-[var(--bg-card)] p-3 text-center">
                <p className="text-xs text-[var(--text-secondary)]">{item.label}</p>
                <p className="text-lg font-bold">{item.value}</p>
              </div>
            ))}
          </div>

          {/* タイムライン */}
          <div className="space-y-0">
            {timeline.timeline.map((entry, i) => (
              <div key={i} className="flex gap-3 border-l-2 border-[var(--border-color)]/30 pb-4 pl-4 relative">
                <div className="absolute -left-[9px] top-1 rounded-full bg-[var(--bg-main)] p-0.5">
                  {typeIcon(entry.type)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 text-sm">
                    <span className="font-medium">{typeLabel(entry.type)}</span>
                    {entry.data.status != null && (
                      <span className={`text-xs ${statusColor(String(entry.data.status))}`}>
                        {String(entry.data.status)}
                      </span>
                    )}
                    <span className="text-xs text-[var(--text-secondary)]">{formatTime(entry.timestamp)}</span>
                  </div>
                  <div className="mt-1 text-xs text-[var(--text-secondary)] space-y-0.5">
                    {entry.type === "goal_created" && (
                      <p className="break-words">{String(entry.data.raw_goal || "")}</p>
                    )}
                    {entry.type === "task" && (
                      <>
                        <p>{String(entry.data.task_type || "")} / ノード: {String(entry.data.assigned_node || "?")}</p>
                        {entry.data.quality_score != null && <p>品質: {Number(entry.data.quality_score).toFixed(2)}</p>}
                        {entry.data.output_preview && (
                          <p className="line-clamp-2 break-words">{String(entry.data.output_preview)}</p>
                        )}
                      </>
                    )}
                    {entry.type === "event" && (
                      <p>{String(entry.data.event_type || "")} [{String(entry.data.severity || "")}] {String(entry.data.source_node || "")}</p>
                    )}
                    {entry.type === "llm_call" && (
                      <p>{String(entry.data.model || "")} (Tier {String(entry.data.tier || "?")}) ¥{Number(entry.data.cost_jpy || 0).toFixed(2)}</p>
                    )}
                    {entry.type === "approval" && (
                      <p>{String(entry.data.request_type || "")} → {String(entry.data.status || "")}</p>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {timeline.timeline.length === 0 && (
            <p className="py-8 text-center text-[var(--text-secondary)]">このゴールのタイムラインは空です</p>
          )}
        </>
      )}

      {!timeline && !loading && selectedGoalId && (
        <p className="py-8 text-center text-[var(--text-secondary)]">タイムラインを読み込めませんでした</p>
      )}
    </div>
  );
}

export default function TimelinePage() {
  return (
    <Suspense fallback={<div className="flex h-[60vh] items-center justify-center"><div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--accent-purple)] border-t-transparent" /></div>}>
      <TimelinePageInner />
    </Suspense>
  );
}
