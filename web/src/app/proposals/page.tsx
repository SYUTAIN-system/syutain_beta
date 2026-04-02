"use client";

import { useEffect, useState, useCallback } from "react";
import { FileStack, ShieldAlert, CheckCircle2, XCircle, Filter } from "lucide-react";
import ProposalCard from "@/components/ProposalCard";
import ApprovalItem from "@/components/ApprovalItem";
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
  const [error, setError] = useState<string | null>(null);
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
    } catch {
      setError("承認処理に失敗しました");
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
    } catch {
      setError("却下処理に失敗しました");
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
      const res = await apiFetch(`/api/proposals/${id}/approve`, { method: "POST" });
      if (res.ok) {
        setProposals((prev) => prev.map((p) => (p.id === id ? { ...p, status: "approved" } : p)));
      }
    } catch {
      setError("承認処理に失敗しました");
    }
  };

  const handleReject = async (id: string) => {
    try {
      const res = await apiFetch(`/api/proposals/${id}/reject`, { method: "POST" });
      if (res.ok) {
        setProposals((prev) => prev.map((p) => (p.id === id ? { ...p, status: "rejected" } : p)));
      }
    } catch {
      setError("却下処理に失敗しました");
    }
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
      {/* Error Banner */}
      {error && (
        <div className="flex items-center justify-between rounded-lg bg-[var(--accent-red)]/10 border border-[var(--accent-red)]/30 px-4 py-3">
          <span className="text-sm text-[var(--accent-red)]">{error}</span>
          <button onClick={() => setError(null)} className="min-h-[44px] min-w-[44px] flex items-center justify-center text-[var(--accent-red)]" aria-label="エラーを閉じる">
            <span className="text-lg">&times;</span>
          </button>
        </div>
      )}
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
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <ShieldAlert className="h-5 w-5 text-[var(--accent-amber)]" />
            承認キュー
            {pendingApprovalCount > 0 && (
              <span className="rounded-full bg-[var(--accent-amber)]/10 px-2 py-0.5 text-xs text-[var(--accent-amber)]">
                {pendingApprovalCount}件待ち
              </span>
            )}
          </h2>
          <div className="flex items-center gap-1 overflow-x-auto scrollbar-hide">
            <Filter className="h-4 w-4 text-[var(--text-secondary)] flex-shrink-0" />
            {filterTabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setApprovalFilter(tab.key)}
                className={`rounded-lg px-3 py-2 text-xs whitespace-nowrap transition-colors min-h-[36px] ${
                  approvalFilter === tab.key
                    ? "bg-[var(--accent-purple)]/20 text-[var(--accent-purple)]"
                    : "text-[var(--text-secondary)] hover:bg-[var(--bg-primary)]"
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
          taskApprovals.map((a) => {
            const cleanText = (text: string) =>
              text.replace(/```[\s\S]*?```/g, "").replace(/[{}"\\[\]]/g, "").replace(/\n{3,}/g, "\n\n").trim();
            const displayContent = a.description || a.content || "承認リクエスト";
            const summary = cleanText(displayContent).slice(0, 200);
            const hasMore = cleanText(displayContent).length > 200;
            return (
            <ApprovalItem
              key={a.approval_id}
              approval={a}
              summary={summary}
              fullText={cleanText(displayContent)}
              hasMore={hasMore}
              typeLabel={typeLabel(a.request_type)}
              statusBadge={statusBadge(a.status)}
              onApprove={handleTaskApprove}
              onReject={handleTaskReject}
            />
            );
          })
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
