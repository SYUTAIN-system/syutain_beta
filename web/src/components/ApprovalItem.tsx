"use client";

import { useState } from "react";
import { CheckCircle, XCircle, ChevronDown, ChevronUp, Clock, Tag } from "lucide-react";

interface Approval {
  approval_id: number;
  request_type: string;
  status: string;
  description: string;
  content: string;
  preview?: string;
  task_id: string;
  task_type: string;
  goal_id: string;
  assigned_node: string;
  requested_at: string;
  responded_at?: string;
  response?: string;
}

interface Props {
  approval: Approval;
  summary: string;
  fullText: string;
  hasMore: boolean;
  typeLabel: string;
  statusBadge: React.ReactNode;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
}

/** 承認リクエスト内容を読みやすくフォーマット */
function formatContent(raw: string): string {
  return raw
    // JSON記号を除去
    .replace(/```[\s\S]*?```/g, "")
    .replace(/[{}"\\[\]]/g, "")
    // キー: 値 を改行して見やすく
    .replace(/,\s*/g, "\n")
    .replace(/:\s*/g, ": ")
    // 連続空行を整理
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

const SNS_TYPES = new Set([
  "sns_post", "bluesky_post", "x_post", "threads_post", "sns_posting", "social_post", "product_publish",
]);

export default function ApprovalItem({
  approval,
  summary,
  fullText,
  hasMore,
  typeLabel,
  statusBadge,
  onApprove,
  onReject,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const isPending = approval.status === "pending";
  const formattedFull = formatContent(fullText);
  const formattedSummary = formatContent(summary);
  const hasPreview = !!(approval.preview && SNS_TYPES.has(approval.request_type));

  return (
    <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] overflow-hidden">
      {/* Header - タップで展開 */}
      <div
        className="flex items-center justify-between px-3 py-2.5 cursor-pointer hover:bg-[var(--bg-primary)]/30 transition-colors sm:px-4 sm:py-3"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {isPending && <Clock className="h-4 w-4 flex-shrink-0 text-[var(--accent-amber)]" />}
          {approval.status === "approved" && <CheckCircle className="h-4 w-4 flex-shrink-0 text-[var(--accent-green)]" />}
          {approval.status === "rejected" && <XCircle className="h-4 w-4 flex-shrink-0 text-[var(--accent-red)]" />}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="rounded bg-[var(--accent-purple)]/10 px-1.5 py-0.5 text-[10px] text-[var(--accent-purple)] flex-shrink-0">
                {typeLabel}
              </span>
              {statusBadge}
              <span className="text-[10px] text-[var(--text-secondary)] flex-shrink-0">
                #{approval.approval_id}
              </span>
            </div>
          </div>
        </div>
        <div className="flex-shrink-0 ml-2">
          {expanded ? (
            <ChevronUp className="h-4 w-4 text-[var(--text-secondary)]" />
          ) : (
            <ChevronDown className="h-4 w-4 text-[var(--text-secondary)]" />
          )}
        </div>
      </div>

      {/* 要約（常に表示） */}
      <div className="border-t border-[var(--border-color)] px-3 py-2 sm:px-4">
        <p className="text-sm leading-relaxed whitespace-pre-wrap break-words">
          {expanded ? formattedFull : formattedSummary}
        </p>
        {!expanded && hasMore && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(true);
            }}
            className="mt-1 text-xs text-[var(--accent-purple)] hover:underline"
          >
            全文を表示
          </button>
        )}
      </div>

      {/* 投稿プレビュー（展開時・SNS/商品タイプのみ） */}
      {expanded && hasPreview && (
        <div className="border-t border-[var(--border-color)] px-3 py-2 sm:px-4">
          <p className="text-[11px] font-medium text-[var(--text-secondary)] mb-1">
            投稿プレビュー
          </p>
          <div
            className="rounded bg-[var(--bg-primary)]/50 px-3 py-2 text-sm leading-relaxed"
            style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}
          >
            {approval.preview}
          </div>
        </div>
      )}

      {/* メタデータ（展開時） */}
      {expanded && (
        <div className="border-t border-[var(--border-color)] px-3 py-2 sm:px-4">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[var(--text-secondary)]">
            {approval.task_id && (
              <span className="flex items-center gap-1">
                <Tag className="h-3 w-3" /> タスク: {String(approval.task_id).slice(0, 8)}
              </span>
            )}
            {approval.goal_id && (
              <span>ゴール: {String(approval.goal_id).slice(0, 8)}</span>
            )}
            {approval.assigned_node && (
              <span>ノード: {String(approval.assigned_node).toUpperCase()}</span>
            )}
            {approval.requested_at && (
              <span>{new Date(approval.requested_at).toLocaleString("ja-JP")}</span>
            )}
          </div>
        </div>
      )}

      {/* 承認/却下ボタン */}
      {isPending && (
        <div className="flex gap-3 border-t border-[var(--border-color)] px-3 py-3 sm:px-4">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onApprove(approval.approval_id);
            }}
            aria-label="承認する"
            className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-[var(--accent-green)]/20 min-h-[48px] px-3 text-base sm:text-sm font-semibold text-[var(--accent-green)] hover:bg-[var(--accent-green)]/30 active:bg-[var(--accent-green)]/40 transition-colors sm:flex-none sm:px-5"
          >
            <CheckCircle className="h-5 w-5 sm:h-4 sm:w-4" /> 承認
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onReject(approval.approval_id);
            }}
            aria-label="却下する"
            className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-[var(--accent-red)]/20 min-h-[48px] px-3 text-base sm:text-sm font-semibold text-[var(--accent-red)] hover:bg-[var(--accent-red)]/30 active:bg-[var(--accent-red)]/40 transition-colors sm:flex-none sm:px-5"
          >
            <XCircle className="h-5 w-5 sm:h-4 sm:w-4" /> 却下
          </button>
        </div>
      )}
    </div>
  );
}
