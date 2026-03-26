"use client";

import { useEffect, useState, useCallback } from "react";
import { FileText, Download, Copy, Filter, X, Check, ChevronDown } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface Artifact {
  id: string;
  type: string;
  title: string;
  content_preview: string;
  quality_score: number | null;
  model: string;
  node: string;
  cost_jpy: number;
  created_at: string;
  word_count: number;
}

interface ArtifactsResponse {
  items: Artifact[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
  publishable_types: string[];
}

interface ArtifactStats {
  total: number;
  avg_quality: number;
  total_cost_jpy: number;
  today_count: number;
  by_type: Record<string, number>;
  by_quality: { high: number; medium: number; low: number };
}

const QUALITY_OPTIONS = [
  { label: "0.50+", value: "0.50" },
  { label: "0.60+", value: "0.60" },
  { label: "0.65+", value: "0.65" },
  { label: "0.70+", value: "0.70" },
];

const SORT_OPTIONS = [
  { label: "新着", value: "newest" },
  { label: "古い順", value: "oldest" },
  { label: "品質↓", value: "quality_desc" },
  { label: "品質↑", value: "quality_asc" },
];

const TASK_TYPE_JP: Record<string, string> = {
  content: "コンテンツ生成",
  research: "調査",
  analysis: "分析",
  pricing: "価格設定",
  coding: "コード作成",
  drafting: "下書き",
  browser_action: "ブラウザ操作",
  strategy: "戦略分析",
};

function qualityColor(score: number): string {
  if (score >= 0.65) return "var(--accent-green)";
  if (score >= 0.50) return "var(--accent-amber)";
  return "var(--accent-red)";
}

export default function ArtifactsPage() {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [stats, setStats] = useState<ArtifactStats | null>(null);
  const [publishableTypes, setPublishableTypes] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [selectedType, setSelectedType] = useState("all");
  const [qualityMin, setQualityMin] = useState("0.50");
  const [sort, setSort] = useState("newest");
  const [selectedArtifact, setSelectedArtifact] = useState<Artifact | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  const perPage = 20;

  const fetchArtifacts = useCallback(
    async (pageNum: number, append: boolean) => {
      if (pageNum === 1) setLoading(true);
      else setLoadingMore(true);

      try {
        const params = new URLSearchParams({
          quality_min: qualityMin,
          sort,
          page: String(pageNum),
          per_page: String(perPage),
        });
        if (selectedType !== "all") params.set("type", selectedType);

        const res = await apiFetch(`/api/artifacts?${params}`);
        if (res.ok) {
          const json: ArtifactsResponse = await res.json();
          if (append) {
            setArtifacts((prev) => [...prev, ...json.items]);
          } else {
            setArtifacts(json.items);
          }
          setHasMore(json.items.length >= perPage);
          if (json.publishable_types && json.publishable_types.length > 0) {
            setPublishableTypes(json.publishable_types);
          }
        }
      } catch {
        // ignore
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [qualityMin, sort, selectedType],
  );

  const fetchStats = useCallback(async () => {
    try {
      const res = await apiFetch("/api/artifacts/stats");
      if (res.ok) {
        const json = await res.json();
        setStats(json);
      }
    } catch {
      // ignore
    }
  }, []);

  // Initial load & filter changes
  useEffect(() => {
    setPage(1);
    fetchArtifacts(1, false);
    fetchStats();
  }, [fetchArtifacts, fetchStats]);

  const loadMore = () => {
    const nextPage = page + 1;
    setPage(nextPage);
    fetchArtifacts(nextPage, true);
  };

  const [detailText, setDetailText] = useState("");

  const openDetail = async (artifact: Artifact) => {
    setDetailLoading(true);
    setSelectedArtifact(artifact);
    setDetailText(artifact.content_preview || "");
    try {
      const res = await apiFetch(`/api/tasks/${artifact.id}`);
      if (res.ok) {
        const detail = await res.json();
        const od = detail.output_data;
        if (typeof od === "string") setDetailText(od);
        else if (od && typeof od === "object") setDetailText(od.text || od.content || JSON.stringify(od, null, 2));
      }
    } catch {
      // keep preview text
    } finally {
      setDetailLoading(false);
    }
  };

  const copyContent = async (content: string) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  };

  const downloadArtifact = async (id: string, type: string) => {
    try {
      const res = await apiFetch(`/api/artifacts/${id}/download`);
      if (!res.ok) return;
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${type}_${id.slice(0, 8)}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      // ignore
    }
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
      {/* Header */}
      <div>
        <h1 className="text-xl sm:text-2xl font-bold">商品化可能な成果物</h1>
        {stats && (
          <div className="mt-1 flex items-center gap-3 text-sm text-[var(--text-secondary)]">
            <span>{stats.total}件</span>
            <span className="h-3 w-px bg-[var(--border-color)]" />
            <span>
              平均品質{" "}
              <span style={{ color: qualityColor(stats.avg_quality) }}>
                {stats.avg_quality.toFixed(2)}
              </span>
            </span>
          </div>
        )}
      </div>

      {/* Type filter pills */}
      {publishableTypes.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-2 -mx-4 px-4 scrollbar-hide">
          <button
            onClick={() => setSelectedType("all")}
            className={`flex-shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
              selectedType === "all"
                ? "bg-[var(--accent-purple)] text-white"
                : "border border-[var(--border-color)] bg-[var(--bg-secondary)] text-[var(--text-secondary)] active:bg-[var(--bg-card)]"
            }`}
          >
            全て
          </button>
          {publishableTypes.map((t) => (
            <button
              key={t}
              onClick={() => setSelectedType(t)}
              className={`flex-shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                selectedType === t
                  ? "bg-[var(--accent-purple)] text-white"
                  : "border border-[var(--border-color)] bg-[var(--bg-secondary)] text-[var(--text-secondary)] active:bg-[var(--bg-card)]"
              }`}
            >
              {TASK_TYPE_JP[t] || t}
            </button>
          ))}
        </div>
      )}

      {/* Filter bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
          <Filter className="h-3.5 w-3.5" />
          <span>フィルター</span>
        </div>
        <div className="relative">
          <select
            value={qualityMin}
            onChange={(e) => setQualityMin(e.target.value)}
            className="appearance-none rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-1.5 pr-7 text-xs text-[var(--text-primary)] outline-none focus:border-[var(--accent-purple)]"
          >
            {QUALITY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                品質 {o.label}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--text-secondary)]" />
        </div>
        <div className="relative">
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            className="appearance-none rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-1.5 pr-7 text-xs text-[var(--text-primary)] outline-none focus:border-[var(--accent-purple)]"
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--text-secondary)]" />
        </div>
      </div>

      {/* Artifact cards */}
      {artifacts.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-[var(--text-secondary)]">
          <FileText className="h-12 w-12 mb-3 opacity-30" />
          <p className="text-sm">条件に一致する成果物はありません</p>
        </div>
      ) : (
        <div className="space-y-3">
          {artifacts.map((a) => (
            <button
              key={a.id}
              onClick={() => openDetail(a)}
              className="w-full text-left rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4 hover:border-[var(--accent-purple)]/50 active:bg-[var(--bg-primary)] transition-colors"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="flex-shrink-0 rounded-full bg-[var(--accent-blue)]/10 px-2 py-0.5 text-[10px] font-medium text-[var(--accent-blue)]">
                      {TASK_TYPE_JP[a.type] || a.type}
                    </span>
                  </div>
                  <p className="font-medium text-sm truncate">
                    {a.title || `${TASK_TYPE_JP[a.type] || a.type} #${a.id.slice(0, 8)}`}
                  </p>
                  <p className="text-xs text-[var(--text-secondary)] mt-0.5">
                    {a.model || "-"} / {a.node || "-"}
                    {a.cost_jpy > 0 ? ` / ¥${a.cost_jpy.toFixed(2)}` : ""}
                  </p>
                  {/* Quality bar */}
                  <div className="flex items-center gap-2 mt-2">
                    <div className="h-1.5 flex-1 max-w-[120px] rounded-full bg-[var(--bg-primary)]">
                      <div
                        className="h-1.5 rounded-full transition-all"
                        style={{
                          width: `${Math.min((a.quality_score ?? 0) * 100, 100)}%`,
                          backgroundColor: qualityColor((a.quality_score ?? 0)),
                        }}
                      />
                    </div>
                    <span
                      className="text-[10px] font-medium"
                      style={{ color: qualityColor((a.quality_score ?? 0)) }}
                    >
                      {(a.quality_score ?? 0).toFixed(2)}
                    </span>
                  </div>
                  {a.content_preview && (
                    <p className="mt-2 text-xs text-[var(--text-secondary)] line-clamp-2">
                      {a.content_preview}
                    </p>
                  )}
                </div>
                <div className="flex flex-col gap-1.5 flex-shrink-0">
                  <span className="rounded-lg border border-[var(--border-color)] px-2.5 py-1 text-[10px] font-medium text-[var(--text-secondary)]">
                    詳細
                  </span>
                  <button
                    onClick={(e) => { e.stopPropagation(); downloadArtifact(a.id, a.type); }}
                    className="flex items-center justify-center rounded-lg border border-[var(--border-color)] px-2.5 py-1 text-[10px] font-medium text-[var(--text-secondary)] hover:text-white hover:border-[var(--accent-purple)] transition-colors"
                  >
                    <Download className="h-3 w-3" />
                  </button>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {/* Pagination */}
      {hasMore && artifacts.length > 0 && (
        <div className="flex justify-center pt-2 pb-4">
          <button
            onClick={loadMore}
            disabled={loadingMore}
            className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] px-6 py-2.5 text-sm font-medium text-[var(--text-secondary)] hover:text-white hover:border-[var(--accent-purple)] transition-colors disabled:opacity-50"
          >
            {loadingMore ? (
              <span className="flex items-center gap-2">
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--accent-purple)] border-t-transparent" />
                読み込み中...
              </span>
            ) : (
              "さらに読み込む"
            )}
          </button>
        </div>
      )}

      {/* Detail Modal */}
      {selectedArtifact && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          {/* Backdrop (desktop) */}
          <div
            className="hidden md:block fixed inset-0 bg-black/60"
            onClick={() => setSelectedArtifact(null)}
          />
          {/* Modal */}
          <div className="fixed inset-0 z-50 bg-[var(--bg-primary)] overflow-y-auto md:static md:inset-auto md:z-auto md:w-full md:max-w-2xl md:max-h-[80vh] md:rounded-xl md:border md:border-[var(--border-color)] md:bg-[var(--bg-card)] md:overflow-y-auto md:shadow-2xl">
            {/* Header */}
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-[var(--border-color)] bg-[var(--bg-primary)] px-4 py-3 md:bg-[var(--bg-card)] md:rounded-t-xl">
              <h2 className="text-lg font-bold truncate">
                {selectedArtifact.title ||
                  `${TASK_TYPE_JP[selectedArtifact.type] || selectedArtifact.type}`}
              </h2>
              <button
                onClick={() => setSelectedArtifact(null)}
                className="flex h-9 w-9 items-center justify-center rounded-lg hover:bg-[var(--bg-primary)] transition-colors"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            {/* Body */}
            <div className="p-4 space-y-4">
              {detailLoading && (
                <div className="flex justify-center py-4">
                  <div className="h-6 w-6 animate-spin rounded-full border-2 border-[var(--accent-purple)] border-t-transparent" />
                </div>
              )}
              {/* Meta info */}
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="text-xs text-[var(--text-secondary)]">タイプ</p>
                  <p className="font-medium">{TASK_TYPE_JP[selectedArtifact.type] || selectedArtifact.type}</p>
                </div>
                <div>
                  <p className="text-xs text-[var(--text-secondary)]">モデル</p>
                  <p className="font-medium">{selectedArtifact.model || "-"}</p>
                </div>
                <div>
                  <p className="text-xs text-[var(--text-secondary)]">ノード</p>
                  <p className="font-medium">{selectedArtifact.node || "-"}</p>
                </div>
                <div>
                  <p className="text-xs text-[var(--text-secondary)]">コスト</p>
                  <p className="font-medium">
                    {selectedArtifact.cost_jpy != null
                      ? `¥${Number(selectedArtifact.cost_jpy).toFixed(2)}`
                      : "-"}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-[var(--text-secondary)]">文字数</p>
                  <p className="font-medium">
                    {selectedArtifact.word_count != null
                      ? `${selectedArtifact.word_count.toLocaleString()}文字`
                      : "-"}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-[var(--text-secondary)]">作成日時</p>
                  <p className="font-medium">
                    {selectedArtifact.created_at
                      ? new Date(selectedArtifact.created_at).toLocaleString("ja-JP")
                      : "-"}
                  </p>
                </div>
              </div>

              {/* Quality bar */}
              <div>
                <p className="text-xs text-[var(--text-secondary)] mb-1.5">品質スコア</p>
                <div className="flex items-center gap-3">
                  <div className="h-2 flex-1 rounded-full bg-[var(--bg-primary)]">
                    <div
                      className="h-2 rounded-full transition-all"
                      style={{
                        width: `${Math.min((selectedArtifact.quality_score || 0) * 100, 100)}%`,
                        backgroundColor: qualityColor(selectedArtifact.quality_score || 0),
                      }}
                    />
                  </div>
                  <span
                    className="text-sm font-bold"
                    style={{ color: qualityColor(selectedArtifact.quality_score || 0) }}
                  >
                    {(selectedArtifact.quality_score || 0).toFixed(2)}
                  </span>
                </div>
              </div>

              {/* Content */}
              <div>
                <p className="text-xs text-[var(--text-secondary)] mb-2">出力内容</p>
                <div className="max-h-96 overflow-y-auto rounded-lg border border-[var(--border-color)] bg-[var(--bg-primary)] p-3">
                  <pre className="text-xs sm:text-sm whitespace-pre-wrap break-words text-[var(--text-primary)]">
                    {detailText}
                  </pre>
                </div>
              </div>

              {/* Action buttons */}
              <div className="flex gap-3">
                <button
                  onClick={() => downloadArtifact(selectedArtifact.id, selectedArtifact.type)}
                  className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-[var(--accent-purple)] h-12 text-sm font-medium text-white hover:bg-[var(--accent-purple)]/80 active:bg-[var(--accent-purple)]/60 transition-colors"
                >
                  <Download className="h-4 w-4" />
                  ダウンロード
                </button>
                <button
                  onClick={() =>
                    copyContent(detailText)
                  }
                  className="flex items-center justify-center gap-2 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] h-12 px-5 text-sm font-medium text-[var(--text-secondary)] hover:text-white hover:border-[var(--accent-purple)] transition-colors"
                >
                  {copied ? (
                    <>
                      <Check className="h-4 w-4 text-[var(--accent-green)]" />
                      <span className="text-[var(--accent-green)]">コピー済</span>
                    </>
                  ) : (
                    <>
                      <Copy className="h-4 w-4" />
                      コピー
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
