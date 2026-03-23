"use client";

import { useState, useEffect } from "react";
import { FileText, CheckCircle, XCircle, Clock, ChevronDown, ChevronUp, Target, Brain } from "lucide-react";
import { apiFetch } from "@/lib/api";

const SCORE_LABELS: Record<string, string> = {
  icp_fit: "ICP適合",
  channel_fit: "チャネル適合",
  content_reuse: "再利用性",
  speed_to_cash: "収益速度",
  gross_margin: "粗利",
  trust_building: "信頼構築",
  continuity_value: "継続性",
};

function parseData(raw: unknown): Record<string, unknown> {
  if (!raw) return {};
  if (typeof raw === "string") {
    try { return JSON.parse(raw); } catch { return { content: raw }; }
  }
  return raw as Record<string, unknown>;
}

function StructuredContent({ data, tab }: { data: unknown; tab: string }) {
  const d = parseData(data);

  if (tab === "proposal") {
    const scoring = d.scoring as Record<string, number> | undefined;
    const whyNow = d.why_now as string[] | undefined;
    const outcome = d.expected_outcome as Record<string, unknown> | undefined;
    const humanActions = d.required_human_actions as string[] | undefined;
    const autoActions = d.auto_actions_allowed as string[] | undefined;
    const hasStructured = scoring || whyNow || outcome;

    if (!hasStructured) {
      return <p className="text-sm whitespace-pre-wrap">{d.content as string || JSON.stringify(d, null, 2)}</p>;
    }
    return (
      <div className="space-y-3 text-sm">
        {scoring && (
          <div>
            <p className="text-xs text-[var(--text-secondary)] mb-1">📊 スコア内訳</p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
              {Object.entries(scoring).map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">{SCORE_LABELS[k] || k}</span>
                  <span className="font-medium">{String(v)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {whyNow && whyNow.length > 0 && (
          <div>
            <p className="text-xs text-[var(--text-secondary)] mb-1">🎯 なぜ今やるべきか</p>
            <ul className="space-y-1">
              {whyNow.map((item, i) => <li key={i} className="pl-3 before:content-['•'] before:mr-2 before:text-[var(--accent-purple)]">{item}</li>)}
            </ul>
          </div>
        )}
        {outcome && (
          <div>
            <p className="text-xs text-[var(--text-secondary)] mb-1">💰 期待される成果</p>
            {outcome.revenue_estimate_jpy != null && (
              <p>収益見積り: ¥{Number(outcome.revenue_estimate_jpy).toLocaleString()}</p>
            )}
            {Boolean(outcome.timeline) && <p>期間: {String(outcome.timeline)}</p>}
            {outcome.confidence != null && <p>確信度: {(Number(outcome.confidence) * 100).toFixed(0)}%</p>}
          </div>
        )}
        {humanActions && humanActions.length > 0 && (
          <div>
            <p className="text-xs text-[var(--text-secondary)] mb-1">👤 必要な手動作業</p>
            <ul className="space-y-0.5">
              {humanActions.map((a, i) => <li key={i}>• {a}</li>)}
            </ul>
          </div>
        )}
        {autoActions && autoActions.length > 0 && (
          <div>
            <p className="text-xs text-[var(--text-secondary)] mb-1">🤖 自動実行可能</p>
            <ul className="space-y-0.5">
              {autoActions.map((a, i) => <li key={i}>• {a}</li>)}
            </ul>
          </div>
        )}
      </div>
    );
  }

  if (tab === "counter") {
    const risks = d.risks as string[] | undefined;
    const dontDoIf = d.dont_do_if as string[] | undefined;
    const failConditions = d.failure_conditions as string[] | undefined;
    const oppCost = d.opportunity_cost as string | undefined;
    const hasStructured = risks || dontDoIf || failConditions;

    if (!hasStructured) {
      return <p className="text-sm whitespace-pre-wrap">{d.content as string || JSON.stringify(d, null, 2)}</p>;
    }
    return (
      <div className="space-y-3 text-sm">
        {risks && risks.length > 0 && (
          <div>
            <p className="text-xs text-[var(--text-secondary)] mb-1">⚠️ リスク</p>
            <ul className="space-y-1">
              {risks.map((r, i) => <li key={i}>• {r}</li>)}
            </ul>
          </div>
        )}
        {dontDoIf && dontDoIf.length > 0 && (
          <div>
            <p className="text-xs text-[var(--text-secondary)] mb-1">🚫 やめた方がいい条件</p>
            <ul className="space-y-1">
              {dontDoIf.map((r, i) => <li key={i}>• {r}</li>)}
            </ul>
          </div>
        )}
        {failConditions && failConditions.length > 0 && (
          <div>
            <p className="text-xs text-[var(--text-secondary)] mb-1">❌ 失敗条件</p>
            <ul className="space-y-1">
              {failConditions.map((r, i) => <li key={i}>• {r}</li>)}
            </ul>
          </div>
        )}
        {oppCost && <p className="text-[var(--text-secondary)]">💡 機会コスト: {oppCost}</p>}
      </div>
    );
  }

  if (tab === "alternative") {
    const parsed = parseData(data);
    const alts = Array.isArray(parsed) ? parsed : (parsed as Record<string, unknown>).alternatives as unknown[] || [parsed];
    if (!Array.isArray(alts) || alts.length === 0) {
      return <p className="text-sm whitespace-pre-wrap">{JSON.stringify(d, null, 2)}</p>;
    }
    return (
      <div className="space-y-2 text-sm">
        {(alts as Record<string, unknown>[]).map((alt, i) => (
          <div key={i} className="rounded-lg bg-[var(--bg-primary)] p-3">
            <p className="font-medium">📋 {String(alt.title || `代替案${i + 1}`)}</p>
            {Boolean(alt.description) && <p className="mt-1 text-[var(--text-secondary)]">{String(alt.description)}</p>}
            <div className="mt-1 flex gap-3 text-xs text-[var(--text-secondary)]">
              {Boolean(alt.effort) && <span>工数: {String(alt.effort)}</span>}
              {alt.revenue_estimate_jpy != null && <span>収益: ¥{Number(alt.revenue_estimate_jpy).toLocaleString()}</span>}
              {Boolean(alt.trust_building) && <span>信頼構築: {String(alt.trust_building)}</span>}
            </div>
          </div>
        ))}
      </div>
    );
  }

  // フォールバック
  return <p className="text-sm whitespace-pre-wrap">{JSON.stringify(d, null, 2)}</p>;
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

interface Props {
  proposal: Proposal;
  onApprove?: (id: string) => void;
  onReject?: (id: string) => void;
}

export default function ProposalCard({ proposal, onApprove, onReject }: Props) {
  const [activeTab, setActiveTab] = useState<"proposal" | "counter" | "alternative">("proposal");
  const [expanded, setExpanded] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [traceData, setTraceData] = useState<{reasoning: string; context: Record<string, any>; confidence: number | null} | null>(null);

  useEffect(() => {
    if (!expanded || traceData) return;
    apiFetch(`/api/traces?target_id=${proposal.id}&limit=1`)
      .then(r => r.ok ? r.json() : {traces: []})
      .then(d => {
        if (d.traces && d.traces.length > 0) {
          setTraceData(d.traces[0]);
        }
      })
      .catch(() => {});
  }, [expanded, proposal.id, traceData]);

  const isPending = proposal.status === "pending";
  const score = proposal.score ?? 0;

  // 3層構造の表示データ
  const tabs = [
    {
      key: "proposal" as const,
      label: "提案",
      color: "var(--accent-blue)",
      bg: "bg-[var(--accent-blue)]",
      data: proposal.proposal_data ?? (proposal.layers?.local_draft ? { content: proposal.layers.local_draft } : null),
    },
    {
      key: "counter" as const,
      label: "反論",
      color: "var(--accent-amber)",
      bg: "bg-[var(--accent-amber)]",
      data: proposal.counter_data ?? (proposal.layers?.api_refined ? { content: proposal.layers.api_refined } : null),
    },
    {
      key: "alternative" as const,
      label: "代替案",
      color: "var(--accent-green)",
      bg: "bg-[var(--accent-green)]",
      data: proposal.alternative_data ?? (proposal.layers?.final ? { content: proposal.layers.final } : null),
    },
  ];

  const activeData = tabs.find((t) => t.key === activeTab)?.data;

  return (
    <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] overflow-hidden">
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-[var(--bg-primary)]/30 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2 min-w-0">
          <FileText className="h-4 w-4 flex-shrink-0 text-[var(--accent-purple)]" />
          <span className="font-semibold truncate">{proposal.title ?? "提案"}</span>
          {score > 0 && (
            <span className="flex items-center gap-0.5 flex-shrink-0 rounded-full bg-[var(--accent-purple)]/10 px-2 py-0.5 text-xs text-[var(--accent-purple)]">
              <Target className="h-3 w-3" />
              {score}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {proposal.status === "approved" && <CheckCircle className="h-4 w-4 text-[var(--accent-green)]" />}
          {proposal.status === "rejected" && <XCircle className="h-4 w-4 text-[var(--accent-red)]" />}
          {isPending && <Clock className="h-4 w-4 text-[var(--accent-amber)]" />}
          <span className="text-xs text-[var(--text-secondary)]">
            {proposal.status === "approved" ? "承認済" : proposal.status === "rejected" ? "却下" : "承認待ち"}
          </span>
          {expanded ? <ChevronUp className="h-4 w-4 text-[var(--text-secondary)]" /> : <ChevronDown className="h-4 w-4 text-[var(--text-secondary)]" />}
        </div>
      </div>

      {/* Summary */}
      {proposal.summary && (
        <div className="border-t border-[var(--border-color)] px-4 py-2">
          <p className="text-sm text-[var(--text-secondary)]">{proposal.summary}</p>
        </div>
      )}

      {expanded && (
        <>
          {/* 3-Layer Tabs */}
          <div className="flex border-t border-[var(--border-color)]">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`flex-1 py-2 text-xs font-medium transition-colors border-b-2 ${
                  activeTab === tab.key
                    ? `border-current text-white`
                    : "border-transparent text-[var(--text-secondary)] hover:text-white"
                }`}
                style={activeTab === tab.key ? { color: tab.color } : undefined}
              >
                {tab.label}
                {tab.data ? "" : " —"}
              </button>
            ))}
          </div>

          {/* Tab Content */}
          <div className="px-4 py-3 min-h-[60px]">
            {activeData ? (
              <StructuredContent data={activeData} tab={activeTab} />
            ) : (
              <p className="text-sm text-[var(--text-secondary)]">データなし</p>
            )}
          </div>

          {/* Revenue Score Bar */}
          {score > 0 && (
            <div className="border-t border-[var(--border-color)] px-4 py-2">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-[var(--text-secondary)]">Revenue Score</span>
                <span className="text-xs font-bold">{score}/100</span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-[var(--bg-primary)]">
                <div
                  className={`h-1.5 rounded-full transition-all ${
                    score >= 70 ? "bg-[var(--accent-green)]" : score >= 40 ? "bg-[var(--accent-amber)]" : "bg-[var(--accent-red)]"
                  }`}
                  style={{ width: `${score}%` }}
                />
              </div>
            </div>
          )}

          {/* なぜこの提案か */}
          <div className="border-t border-[var(--border-color)] px-4 py-2">
            <button
              onClick={() => setTraceOpen(!traceOpen)}
              className="flex items-center gap-1 text-xs text-[var(--accent-purple)]"
            >
              <Brain className="h-3 w-3" />
              なぜこの提案か
              <span>{traceOpen ? "▲" : "▼"}</span>
            </button>
            {traceOpen && traceData && (
              <div className="mt-2 rounded-md bg-[var(--bg-primary)] px-3 py-2 text-xs">
                <p className="text-[var(--text-secondary)] mb-1">{traceData.reasoning}</p>
                {traceData.context && (
                  <div className="text-[10px] text-[var(--text-secondary)] space-y-0.5">
                    {traceData.context.target_icp && <p>ICP: {String(traceData.context.target_icp)}</p>}
                    {traceData.context.primary_channel && <p>チャネル: {String(traceData.context.primary_channel)}</p>}
                    {traceData.context.model_used && <p>モデル: {String(traceData.context.model_used)}</p>}
                    {traceData.context.intel_items_used != null && <p>参照intel: {String(traceData.context.intel_items_used)}件</p>}
                  </div>
                )}
              </div>
            )}
            {traceOpen && !traceData && (
              <p className="mt-1 text-[10px] text-[var(--text-secondary)]">根拠データなし</p>
            )}
          </div>

          {/* Actions */}
          {isPending && (onApprove || onReject) && (
            <div className="flex gap-2 border-t border-[var(--border-color)] px-4 py-3">
              {onApprove && (
                <button
                  onClick={() => onApprove(proposal.id)}
                  className="flex items-center gap-1 rounded-md bg-[var(--accent-green)]/20 px-4 py-1.5 text-sm text-[var(--accent-green)] hover:bg-[var(--accent-green)]/30 transition-colors"
                >
                  <CheckCircle className="h-3.5 w-3.5" /> 承認
                </button>
              )}
              {onReject && (
                <button
                  onClick={() => onReject(proposal.id)}
                  className="flex items-center gap-1 rounded-md bg-[var(--accent-red)]/20 px-4 py-1.5 text-sm text-[var(--accent-red)] hover:bg-[var(--accent-red)]/30 transition-colors"
                >
                  <XCircle className="h-3.5 w-3.5" /> 却下
                </button>
              )}
            </div>
          )}
        </>
      )}

      {/* Footer */}
      <div className="bg-[var(--bg-primary)] px-4 py-2 text-xs text-[var(--text-secondary)]">
        {proposal.created_at ? new Date(proposal.created_at).toLocaleString("ja-JP") : "-"}
      </div>
    </div>
  );
}
