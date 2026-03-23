"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ListChecks, Clock, CheckCircle2, AlertCircle, Loader2, XCircle, ShieldAlert, Copy, Check, Brain } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface Task {
  id: string;
  title?: string;
  type?: string;
  goal_id?: string;
  status: string;
  node?: string;
  assigned_node?: string;
  model_used?: string;
  tier?: string;
  cost_jpy?: number;
  quality_score?: number;
  output_data?: string;
  artifacts?: string;
  created_at?: string;
  updated_at?: string;
}

// タスクタイプ日本語マッピング
const TASK_TYPE_JP: Record<string, string> = {
  monitoring: "監視",
  browser_action: "ブラウザ操作",
  analysis: "分析",
  content: "コンテンツ生成",
  pricing: "価格設定",
  coding: "コード作成",
  research: "調査",
  strategy: "戦略分析",
  drafting: "下書き作成",
  proposal: "提案",
  batch_process: "バッチ処理",
  data_extraction: "データ抽出",
  info_collection: "情報収集",
  note_article: "note記事",
  product_desc: "商品説明",
  translation_draft: "翻訳下書き",
  tagging: "タグ付け",
  classification: "分類",
  computer_use: "PC操作",
  btob: "BtoB提案",
  sns_post: "SNS投稿",
  trading: "取引",
  approval_request: "承認リクエスト",
  goal_packet_draft: "ゴール下書き",
  proposal_generation: "提案生成",
};

function translateTaskType(type?: string): string | undefined {
  if (!type) return undefined;
  return TASK_TYPE_JP[type] ?? type;
}

// APIのstatusをUI用にマッピング
function normalizeStatus(status: string): string {
  const map: Record<string, string> = {
    pending: "queued",
    queued: "queued",
    running: "running",
    completed: "done",
    done: "done",
    success: "done",
    failed: "failed",
    failure: "failed",
    error: "failed",
    waiting_approval: "approval",
    pending_approval: "approval",
  };
  return map[status] ?? "queued";
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return "-";
  try {
    return new Date(dateStr).toLocaleString("ja-JP");
  } catch {
    return "-";
  }
}

const statusConfig: Record<string, { icon: typeof Clock; color: string; bg: string; label: string }> = {
  queued: { icon: Clock, color: "text-[var(--text-secondary)]", bg: "bg-[var(--bg-primary)]", label: "待機中" },
  running: { icon: Loader2, color: "text-[var(--accent-blue)]", bg: "bg-[var(--accent-blue)]/10", label: "実行中" },
  approval: { icon: ShieldAlert, color: "text-[var(--accent-amber)]", bg: "bg-[var(--accent-amber)]/10", label: "承認待ち" },
  done: { icon: CheckCircle2, color: "text-[var(--accent-green)]", bg: "bg-[var(--accent-green)]/10", label: "完了" },
  failed: { icon: AlertCircle, color: "text-[var(--accent-red)]", bg: "bg-[var(--accent-red)]/10", label: "失敗" },
};

export default function TasksPage() {
  const searchParams = useSearchParams();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [outputExpanded, setOutputExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [detailOpened, setDetailOpened] = useState(false);
  const [traces, setTraces] = useState<Array<{id: number; agent_name: string; action: string; reasoning: string; confidence: number | null; context: Record<string, unknown>; created_at: string}>>([]);
  const [tracesOpen, setTracesOpen] = useState(false);

  useEffect(() => {
    const fetchTasks = async () => {
      try {
        const res = await apiFetch("/api/tasks");
        if (!res.ok) throw new Error(`API error: ${res.status}`);
        const json = await res.json();
        const taskList = json?.tasks ?? json;
        if (Array.isArray(taskList)) {
          setTasks(taskList);
        } else {
          setTasks([]);
        }
      } catch (e) {
        setError("タスクの読み込みに失敗しました");
        setTasks([]);
      } finally {
        setLoading(false);
      }
    };
    fetchTasks();
    const interval = setInterval(fetchTasks, 5000);
    return () => clearInterval(interval);
  }, []);

  // ?detail=xxx のクエリパラメータでモーダルを自動オープン
  useEffect(() => {
    if (detailOpened || tasks.length === 0) return;
    const detailId = searchParams.get("detail");
    if (detailId) {
      const found = tasks.find((t) => t.id === detailId);
      if (found) {
        setSelectedTask(found);
        setOutputExpanded(false);
        setCopied(false);
        setDetailOpened(true);
      }
    }
  }, [tasks, searchParams, detailOpened]);

  const filtered = filter === "all"
    ? tasks
    : tasks.filter((t) => normalizeStatus(t.status) === filter);

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--accent-purple)] border-t-transparent" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-[60vh] flex-col items-center justify-center gap-4">
        <XCircle className="h-12 w-12 text-[var(--accent-red)]" />
        <p className="text-[var(--text-secondary)]">{error}</p>
        <button
          onClick={() => window.location.reload()}
          className="rounded-lg bg-[var(--accent-purple)] px-4 py-2 text-sm text-white"
        >
          再読み込み
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <ListChecks className="h-6 w-6 text-[var(--accent-purple)]" />
        <h1 className="text-2xl font-bold">タスク一覧</h1>
      </div>
      <div className="overflow-x-auto">
        <div className="flex gap-1 rounded-lg bg-[var(--bg-card)] p-1 w-max">
          {["all", "running", "approval", "queued", "done", "failed"].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-md px-3 py-1 text-xs whitespace-nowrap transition-colors ${
                filter === f ? "bg-[var(--accent-purple)] text-white" : "text-[var(--text-secondary)] hover:text-white"
              }`}
            >
              {f === "all" ? "全て" : statusConfig[f]?.label ?? f}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        {filtered.map((task) => {
          const uiStatus = normalizeStatus(task.status);
          const cfg = statusConfig[uiStatus] ?? statusConfig.queued;
          const Icon = cfg.icon;
          const displayTitle = task.title ?? translateTaskType(task.type) ?? task.goal_id ?? task.id;
          const displayNode = task.node ?? task.assigned_node ?? "-";
          return (
            <div
              key={task.id}
              onClick={() => {
                setSelectedTask(task); setOutputExpanded(false); setCopied(false); setTracesOpen(false);
                apiFetch(`/api/traces?target_id=${task.id}`).then(r => r.ok ? r.json() : {traces:[]}).then(d => setTraces(d.traces || [])).catch(() => setTraces([]));
              }}
              className="flex cursor-pointer items-center justify-between rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] px-4 py-3 hover:border-[var(--accent-purple)]/50 transition-colors"
            >
              <div className="flex items-center gap-3 min-w-0">
                <Icon className={`h-5 w-5 flex-shrink-0 ${cfg.color} ${uiStatus === "running" ? "animate-spin" : ""}`} />
                <div className="min-w-0">
                  <p className="font-medium truncate">{displayTitle}</p>
                  <p className="text-xs text-[var(--text-secondary)] truncate">
                    {displayNode} &middot; {formatDate(task.updated_at ?? task.created_at)}
                    {task.model_used ? ` · ${task.model_used}` : ""}
                  </p>
                </div>
              </div>
              <span className={`flex-shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${cfg.bg} ${cfg.color}`}>
                {cfg.label}
              </span>
            </div>
          );
        })}
        {filtered.length === 0 && (
          <p className="py-12 text-center text-[var(--text-secondary)]">タスクはまだありません</p>
        )}
      </div>

      {/* タスク詳細モーダル */}
      {selectedTask && (() => {
        let outputText = "";
        if (selectedTask.output_data) {
          try {
            const output = typeof selectedTask.output_data === "string"
              ? JSON.parse(selectedTask.output_data)
              : selectedTask.output_data;
            outputText = output?.text || output?.content || output?.message || JSON.stringify(output, null, 2);
          } catch {
            outputText = String(selectedTask.output_data);
          }
        }
        const isLong = outputText.length > 500;
        const displayText = isLong && !outputExpanded ? outputText.slice(0, 500) + "..." : outputText;

        return (
          <div className="fixed inset-0 z-50">
            {/* 背景オーバーレイ — タッチイベント干渉防止のためonTouchEndで閉じる */}
            <div
              className="absolute inset-0 bg-black/60"
              onTouchEnd={() => setSelectedTask(null)}
              onClick={() => setSelectedTask(null)}
            />
            {/* モーダル本体 */}
            <div className="absolute inset-x-0 bottom-0 sm:inset-auto sm:top-1/2 sm:left-1/2 sm:-translate-x-1/2 sm:-translate-y-1/2 sm:w-full sm:max-w-md">
              <div
                className="rounded-t-xl sm:rounded-xl border border-[var(--border-color)] bg-[var(--bg-card)] flex flex-col"
                style={{ maxHeight: "92dvh" }}
              >
                {/* 固定ヘッダー */}
                <div className="flex-shrink-0 p-4 sm:p-6 pb-2 sm:pb-2 border-b border-[var(--border-color)]">
                  <div className="flex justify-center sm:hidden mb-2">
                    <div className="h-1 w-10 rounded-full bg-[var(--text-secondary)]/30" />
                  </div>
                  <div className="flex items-center justify-between">
                    <h3 className="font-bold text-lg">タスク詳細</h3>
                    <button
                      onTouchEnd={(e) => { e.preventDefault(); setSelectedTask(null); }}
                      onClick={() => setSelectedTask(null)}
                      className="text-[var(--text-secondary)] hover:text-white p-2 -mr-2"
                    >
                      <XCircle className="h-5 w-5" />
                    </button>
                  </div>
                </div>

                {/* スクロール領域 */}
                <div
                  className="flex-1 overflow-y-auto p-4 sm:p-6 pt-3 sm:pt-3 space-y-3"
                  style={{ WebkitOverflowScrolling: "touch" }}
                >
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between gap-2"><span className="text-[var(--text-secondary)] flex-shrink-0">ID</span><span className="font-mono text-xs text-right break-all">{selectedTask.id}</span></div>
                    <div className="flex justify-between gap-2"><span className="text-[var(--text-secondary)] flex-shrink-0">タイプ</span><span>{translateTaskType(selectedTask.type) ?? "-"}</span></div>
                    <div className="flex justify-between gap-2"><span className="text-[var(--text-secondary)] flex-shrink-0">ステータス</span><span>{statusConfig[normalizeStatus(selectedTask.status)]?.label ?? selectedTask.status}</span></div>
                    <div className="flex justify-between gap-2"><span className="text-[var(--text-secondary)] flex-shrink-0">ノード</span><span>{selectedTask.node ?? selectedTask.assigned_node ?? "-"}</span></div>
                    <div className="flex justify-between gap-2"><span className="text-[var(--text-secondary)] flex-shrink-0">モデル</span><span className="text-right break-all">{selectedTask.model_used ?? "-"}</span></div>
                    <div className="flex justify-between gap-2"><span className="text-[var(--text-secondary)] flex-shrink-0">Tier</span><span>{selectedTask.tier ?? "-"}</span></div>
                    <div className="flex justify-between gap-2"><span className="text-[var(--text-secondary)] flex-shrink-0">コスト</span><span>{selectedTask.cost_jpy != null ? `¥${selectedTask.cost_jpy.toFixed(2)}` : "-"}</span></div>
                    <div className="flex justify-between gap-2"><span className="text-[var(--text-secondary)] flex-shrink-0">品質スコア</span><span>{selectedTask.quality_score != null ? selectedTask.quality_score.toFixed(2) : "-"}</span></div>
                    <div className="flex justify-between gap-2"><span className="text-[var(--text-secondary)] flex-shrink-0">作成日時</span><span className="text-right">{formatDate(selectedTask.created_at)}</span></div>
                    <div className="flex justify-between gap-2"><span className="text-[var(--text-secondary)] flex-shrink-0">更新日時</span><span className="text-right">{formatDate(selectedTask.updated_at)}</span></div>
                  </div>

                  {/* 成果物 */}
                  {outputText && (
                    <div className="mt-4">
                      <div className="mb-2 flex items-center justify-between">
                        <p className="text-sm font-semibold text-[var(--accent-green)]">成果物</p>
                        <button
                          onTouchEnd={(e) => {
                            e.preventDefault();
                            navigator.clipboard.writeText(outputText);
                            setCopied(true);
                            setTimeout(() => setCopied(false), 2000);
                          }}
                          onClick={() => {
                            navigator.clipboard.writeText(outputText);
                            setCopied(true);
                            setTimeout(() => setCopied(false), 2000);
                          }}
                          className="flex items-center gap-1 rounded-md bg-[var(--bg-primary)] px-2 py-1 text-xs text-[var(--text-secondary)] hover:text-white transition-colors"
                        >
                          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                          {copied ? "コピー済" : "コピー"}
                        </button>
                      </div>
                      <div className="rounded-lg bg-[var(--bg-primary)] p-3 text-xs whitespace-pre-wrap leading-relaxed break-words">
                        {displayText}
                      </div>
                      {isLong && (
                        <button
                          onTouchEnd={(e) => { e.preventDefault(); setOutputExpanded(!outputExpanded); }}
                          onClick={() => setOutputExpanded(!outputExpanded)}
                          className="mt-2 w-full text-center py-3 text-xs text-[var(--accent-purple)] active:opacity-70"
                        >
                          {outputExpanded ? "折りたたむ" : "全文を表示"}
                        </button>
                      )}
                    </div>
                  )}

                  {/* 判断根拠 */}
                  <div className="mt-4">
                    <button
                      onClick={() => setTracesOpen(!tracesOpen)}
                      className="flex items-center gap-1 text-sm font-semibold text-[var(--accent-purple)]"
                    >
                      <Brain className="h-4 w-4" />
                      判断根拠 ({traces.length}件)
                      <span className="text-xs">{tracesOpen ? "▲" : "▼"}</span>
                    </button>
                    {tracesOpen && traces.length > 0 && (
                      <div className="mt-2 space-y-2">
                        {traces.map((t) => {
                          const confColor = t.confidence == null ? "text-[var(--text-secondary)]"
                            : t.confidence >= 0.8 ? "text-[var(--accent-green)]"
                            : t.confidence >= 0.5 ? "text-[var(--accent-amber)]"
                            : "text-[var(--accent-red)]";
                          return (
                            <div key={t.id} className="rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-2 text-xs">
                              <div className="flex items-center justify-between mb-1">
                                <span className="font-mono text-[var(--accent-purple)]">{t.agent_name}</span>
                                <span className={`font-bold ${confColor}`}>
                                  {t.confidence != null ? `${(t.confidence * 100).toFixed(0)}%` : "-"}
                                </span>
                              </div>
                              <p className="text-[var(--text-secondary)] mb-1">{t.reasoning}</p>
                              {t.context && Object.keys(t.context).length > 0 && (
                                <details className="text-[10px] text-[var(--text-secondary)]">
                                  <summary className="cursor-pointer">詳細コンテキスト</summary>
                                  <pre className="mt-1 whitespace-pre-wrap break-all">{JSON.stringify(t.context, null, 2)}</pre>
                                </details>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                    {tracesOpen && traces.length === 0 && (
                      <p className="mt-2 text-xs text-[var(--text-secondary)]">判断根拠はまだ記録されていません</p>
                    )}
                  </div>
                </div>

                {/* 固定フッター — 閉じるボタン */}
                <div className="flex-shrink-0 p-4 sm:p-6 pt-2 sm:pt-2 border-t border-[var(--border-color)]">
                  <button
                    onTouchEnd={(e) => { e.preventDefault(); setSelectedTask(null); }}
                    onClick={() => setSelectedTask(null)}
                    className="w-full rounded-lg bg-[var(--accent-purple)] py-3 text-sm font-medium text-white active:opacity-70"
                  >
                    閉じる
                  </button>
                </div>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
