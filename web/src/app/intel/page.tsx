"use client";

import { useEffect, useState } from "react";
import { Search, Globe, Mail, Star, Filter } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface IntelItem {
  id: string;
  source: string;
  title: string;
  summary?: string;
  importance: number;
  review_flag?: string;
  url?: string;
  created_at: string;
}

const SOURCES = [
  { key: "all", label: "全て" },
  { key: "gmail", label: "Gmail" },
  { key: "tavily", label: "Tavily" },
  { key: "jina", label: "Jina" },
  { key: "youtube", label: "YouTube" },
  { key: "rss", label: "RSS" },
];

function importanceBadge(score: number) {
  // importance_scoreは0.0-1.0のスケール
  if (score >= 0.7) {
    return { label: "重要", className: "bg-[var(--accent-red)]/10 text-[var(--accent-red)]" };
  }
  if (score >= 0.4) {
    return { label: "中", className: "bg-yellow-500/10 text-yellow-500" };
  }
  return { label: "低", className: "bg-[var(--text-secondary)]/10 text-[var(--text-secondary)]" };
}

function sourceIcon(source: string) {
  switch (source.toLowerCase()) {
    case "gmail":
      return <Mail className="h-4 w-4" />;
    case "tavily":
    case "jina":
    case "web":
      return <Globe className="h-4 w-4" />;
    default:
      return <Search className="h-4 w-4" />;
  }
}

export default function IntelPage() {
  const [items, setItems] = useState<IntelItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await apiFetch("/api/intel");
        if (!res.ok) throw new Error("API error");
        const json = await res.json();
        const list = json.items ?? json.intel ?? json;
        if (Array.isArray(list)) {
          setItems(list);
        }
      } catch {
        setItems([]);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const filtered = filter === "all" ? items : items.filter((item) => item.source?.toLowerCase().startsWith(filter.toLowerCase()));

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--accent-purple)] border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Search className="h-6 w-6 text-[var(--accent-purple)]" />
        <h1 className="text-2xl font-bold">情報収集</h1>
      </div>

      {/* Source Filter */}
      <div className="overflow-x-auto">
        <div className="flex gap-1 rounded-lg bg-[var(--bg-card)] p-1 w-max">
          {SOURCES.map((src) => (
            <button
              key={src.key}
              onClick={() => setFilter(src.key)}
              className={`flex items-center gap-1 rounded-md px-3 py-1 text-xs whitespace-nowrap transition-colors ${
                filter === src.key
                  ? "bg-[var(--accent-purple)] text-white"
                  : "text-[var(--text-secondary)] hover:text-white"
              }`}
            >
              {src.key === "all" ? (
                <>
                  <Filter className="h-3 w-3" />
                  {src.label}
                </>
              ) : (
                <>
                  {sourceIcon(src.key)}
                  {src.label}
                </>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Intel Items */}
      <div className="space-y-2">
        {filtered.map((item) => {
          const badge = importanceBadge(item.importance);
          return (
            <div
              key={item.id}
              className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] px-4 py-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3 min-w-0">
                  <div className="mt-0.5 text-[var(--text-secondary)]">
                    {sourceIcon(item.source)}
                  </div>
                  <div className="min-w-0">
                    <p className="font-medium truncate">
                      {item.url ? (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="hover:text-[var(--accent-purple)] transition-colors"
                        >
                          {item.title}
                        </a>
                      ) : (
                        item.title
                      )}
                    </p>
                    {item.summary && (
                      <p className="mt-1 text-sm text-[var(--text-secondary)] line-clamp-2">
                        {item.summary}
                      </p>
                    )}
                    <p className="mt-1 text-xs text-[var(--text-secondary)]">
                      {item.source} &middot; {new Date(item.created_at).toLocaleString("ja-JP")}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {item.review_flag && item.review_flag !== "no_review_needed" && (
                    <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                      item.review_flag === "pending_review"
                        ? "bg-[var(--accent-amber)]/10 text-[var(--accent-amber)]"
                        : item.review_flag === "reviewed"
                        ? "bg-[var(--accent-green)]/10 text-[var(--accent-green)]"
                        : "bg-[var(--text-secondary)]/10 text-[var(--text-secondary)]"
                    }`}>
                      {item.review_flag === "pending_review" ? "未精査" : item.review_flag === "reviewed" ? "精査済" : item.review_flag}
                    </span>
                  )}
                  <div className="flex items-center gap-1 text-xs text-[var(--text-secondary)]">
                    <Star className="h-3 w-3" />
                    {(item.importance * 10).toFixed(1)}
                  </div>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${badge.className}`}>
                    {badge.label}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
        {filtered.length === 0 && (
          <p className="py-12 text-center text-[var(--text-secondary)]">収集した情報はまだありません</p>
        )}
      </div>
    </div>
  );
}
