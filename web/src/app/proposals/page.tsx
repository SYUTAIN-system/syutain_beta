"use client";

import { useEffect, useState, useCallback } from "react";
import { FileStack, ShieldAlert, CheckCircle2, XCircle, Filter } from "lucide-react";
import ProposalCard from "@/components/ProposalCard";
import { apiFetch } from "@/lib/api";

interface TaskApproval {
  approval_id: number;
  request_type: string;
  description: string;
  content: string;
  task_id: string;
  task_type: string;
  goal_id: string;
  assigned_node: string;
  requested_at: string;
  responded_at?: string;
  response?: string;
  status: string;
}

interface Proposal {
  id: string;
  title: string;
  summary?: string;
  layer?: string;
  status: string;
  score?: number;
  proposal_data?: Record<string, unknown>;
  counter_data?: Record<string, unknown>;
  alternative_data?: Record<string, unknown>;
  layers?: {
    local_draft?: string;
    api_refined?: string;
    final?: string;
  };
  created_at?: string;
}

type ApprovalFilter = "pending" | "all" | "approved" | "rejected";

export default function ProposalsPage() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [taskApprovals, setTaskApprovals] = useState<TaskApproval[]>([]);
  const [loading, setLoading] = useState(true);
  const [approvalFilter, setApprovalFilter] = useState<ApprovalFilter>("pending");

  const fetchTaskApprovals = useCallback(async () => {
    try {
      const res = await apiFetch(`/api/pending-approvals?status=${approvalFilter}`);
      if (res.ok) {
        const json = await res.json();
        setTaskApprovals(json.approvals ?? []);
      }
    } catch { /* ignore */ }
  }, [approvalFilter]);

  const handleTaskApprove = async (approvalId: number) => {
    try {
      const res = await apiFetch(`/api/pending-approvals/${approvalId}/respond`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: true }),
      });
      if (res.ok) {
        // 即座にUIを更新
        setTaskApprovals((prev) =>
          prev.map((a) =>
            a.approval_id === approvalId
              ? { ...a, status: "approved" }
              : a
          ).filter((a) => approvalFilter === "all" || a.status === approvalFilter)
        );
        // サーバーから最新状態を再取得
        setTimeout(() => fetchTaskApprovals(), 500);
      }
    } catch (e) {
      console.error("承認エラー:", e);
    }
  };

  const handleTaskReject = async (approvalId: number) => {
    try {
      const res = await apiFetch(`/api/pending-approvals/${approvalId}/respond`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: false }),
      });
      if (res.ok) {
        setTaskApprovals((prev) =>
          prev.map((a) =>
            a.approval_id === approvalId
              ? { ...a, status: "rejected" }
              : a
          ).filter((a) => approvalFilter === "all" || a.status === approvalFilter)
        );
        setTimeout(() => fetchTaskApprovals(), 500);
      }
    } catch (e) {
      console.error("却下エラー:", e);
    }
  };

  useEffect(() => {
    const fetchProposals = async () => {
      try {
        const res = await apiFetch("/api/proposals");
        if (!res.ok) throw new Error("API error");
        const json = await res.json();
        const list = json.proposals ?? json;
        if (Array.isArray(list)) {
          const parseJson = (v: unknown): Record<string, unknown> | undefined => {
            if (typeof v === "string") { try { return JSON.parse(v); } catch { return undefined; } }
            return v as Record<string, unknown> | undefined;
          };
          const mapped: Proposal[] = list.map((p: Record<string, unknown>) => ({
            id: String(p.proposal_id ?? p.id ?? ""),
            title: String(p.title ?? ""),
            summary: p.summary as string | undefined,
            layer: p.layer as string | undefined,
            status: p.adopted === true ? "approved" : p.adopted === false ? "rejected" : "pending",
            score: (p.score ?? 0) as number,
            proposal_data: parseJson(p.proposal_data),
            counter_data: parseJson(p.counter_data),
            alternative_data: parseJson(p.alternative_data),
            created_at: p.created_at as string | undefined,
          }));
          setProposals(mapped);
        } else {
          setProposals([]);
        }
      } catch {
        setProposals([]);
      } finally {
        setLoading(false);
      }
    };
    fetchProposals();
  }, []);

  useEffect(() => {
    fetchTaskApprovals();
    const interval = setInterval(fetchTaskApprovals, 5000);
    return () => clearInterval(interval);
  }, [fetchTaskApprovals]);

  const handleApprove = async (id: string) => {
    try {
      await apiFetch(`/api/proposals/${id}/approve`, { method: "POST" });
    } catch {
      // fallback: update locally
    }
    setProposals((prev) => prev.map((p) => (p.id === id ? { ...p, status: "approved" } : p)));
  };

  const handleReject = async (id: string) => {
    try {
      await apiFetch(`/api/proposals/${id}/reject`, { method: "POST" });
    } catch {
      // fallback: update locally
    }
    setProposals((prev) => prev.map((p) => (p.id === id ? { ...p, status: "rejected" } : p)));
  };

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--accent-purple)] border-t-transparent" />
      </div>
    );
  }

  const pendingCount = proposals.filter((p) => p.status === "pending").length;
  const pendingApprovalCount = taskApprovals.filter((a) => a.status === "pending").length;

  const filterTabs: { key: ApprovalFilter; label: string }[] = [
    { key: "pending", label: "承認待ち" },
    { key: "approved", label: "承認済み" },
    { key: "rejected", label: "却下済み" },
    { key: "all", label: "すべて" },
  ];

  const statusBadge = (status: string) => {
    const map: Record<string, { bg: string; text: string; label: string }> = {
      pending: { bg: "bg-[var(--accent-amber)]/10", text: "text-[var(--accent-amber)]", label: "保留中" },
      approved: { bg: "bg-[var(--accent-green)]/10", text: "text-[var(--accent-green)]", label: "承認済" },
      auto_approved: { bg: "bg-[var(--accent-green)]/10", text: "text-[var(--accent-green)]", label: "自動承認" },
      rejected: { bg: "bg-[var(--accent-red)]/10", text: "text-[var(--accent-red)]", label: "却下" },
      timeout_rejected: { bg: "bg-[var(--accent-red)]/10", text: "text-[var(--accent-red)]", label: "タイムアウト" },
    };
    const s = map[status] || map.pending;
    return <span className={`rounded-full px-2 py-0.5 text-xs ${s.bg} ${s.text}`}>{s.label}</span>;
  };

  const typeLabel = (type: string) => {
    const map: Record<string, string> = {
      bluesky_post: "Bluesky投稿",
      sns_post: "SNS投稿",
      task_approval: "タスク承認",
      product_publish: "商品公開",
      pricing: "価格設定",
    };
    return map[type] || type;
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <FileStack className="h-6 w-6 text-[var(--accent-purple)]" />
        <h1 className="text-2xl font-bold">提案一覧</h1>
        {pendingCount > 0 && (
          <span className="ml-2 rounded-full bg-[var(--accent-amber)]/10 px-2.5 py-0.5 text-xs text-[var(--accent-amber)]">
            {pendingCount} 件承認待ち
          </span>
        )}
      </div>

      {/* 承認キュー */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <ShieldAlert className="h-5 w-5 text-[var(--accent-amber)]" />
            承認キュー
            {pendingApprovalCount > 0 && (
              <span className="rounded-full bg-[var(--accent-amber)]/10 px-2 py-0.5 text-xs text-[var(--accent-amber)]">
                {pendingApprovalCount}件待ち
              </span>
            )}
          </h2>
          <div className="flex items-center gap-1">
            <Filter className="h-4 w-4 text-[var(--text-secondary)]" />
            {filterTabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setApprovalFilter(tab.key)}
                className={`rounded-lg px-2.5 py-1 text-xs transition-colors ${
                  approvalFilter === tab.key
                    ? "bg-[var(--accent-purple)]/20 text-[var(--accent-purple)]"
                    : "text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {taskApprovals.length === 0 ? (
          <p className="py-4 text-center text-sm text-[var(--text-secondary)]">
            {approvalFilter === "pending" ? "承認待ちはありません" : "該当する承認リクエストはありません"}
          </p>
        ) : (
          taskApprovals.map((a) => (
            <div key={a.approval_id} className="rounded-lg border border-[var(--border)]/30 bg-[var(--bg-card)] p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-medium text-[var(--accent-purple)]">{typeLabel(a.request_type)}</span>
                    {statusBadge(a.status)}
                  </div>
                  <p className="font-medium whitespace-pre-wrap break-words">{a.description || a.content || "承認リクエスト"}</p>
                  {a.content && a.content !== a.description && (
                    <p className="mt-1 text-sm text-[var(--text-secondary)] whitespace-pre-wrap break-words line-clamp-3">
                      {a.content}
                    </p>
                  )}
                  <div className="mt-1 flex items-center gap-3 text-xs text-[var(--text-secondary)]">
                    {a.task_id && <span>タスク: {a.task_id}</span>}
                    {a.goal_id && <span>ゴール: {a.goal_id}</span>}
                    {a.assigned_node && <span>ノード: {a.assigned_node}</span>}
                    {a.requested_at && <span>{new Date(a.requested_at).toLocaleString("ja-JP")}</span>}
                  </div>
                  {a.response && a.status !== "pending" && (
                    <p className="mt-1 text-xs text-[var(--text-secondary)]">応答: {a.response}</p>
                  )}
                </div>
                {a.status === "pending" && (
                  <div className="flex flex-shrink-0 gap-2">
                    <button
                      onClick={() => handleTaskApprove(a.approval_id)}
                      className="flex items-center gap-1 rounded-lg bg-[var(--accent-green)]/20 px-3 py-1.5 text-sm text-[var(--accent-green)] hover:bg-[var(--accent-green)]/30"
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" /> 承認
                    </button>
                    <button
                      onClick={() => handleTaskReject(a.approval_id)}
                      className="flex items-center gap-1 rounded-lg bg-[var(--accent-red)]/20 px-3 py-1.5 text-sm text-[var(--accent-red)] hover:bg-[var(--accent-red)]/30"
                    >
                      <XCircle className="h-3.5 w-3.5" /> 却下
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))
        )}
      </div>

      {proposals.length === 0 ? (
        <p className="py-12 text-center text-[var(--text-secondary)]">提案はまだありません</p>
      ) : (
        <div className="space-y-4">
          {proposals.map((p) => (
            <ProposalCard
              key={p.id}
              proposal={p}
              onApprove={p.status === "pending" ? handleApprove : undefined}
              onReject={p.status === "pending" ? handleReject : undefined}
            />
          ))}
        </div>
      )}
    </div>
  );
}
