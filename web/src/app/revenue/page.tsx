"use client";

import { useEffect, useState, useCallback } from "react";
import { DollarSign, TrendingUp, ArrowUpRight, ArrowDownRight, BarChart3, Plus } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface RevenueRecord {
  id: number;
  platform: string;
  product_title: string;
  revenue_jpy: number;
  fee_jpy: number;
  net_revenue_jpy: number;
  platform_order_id: string;
  notes: string;
  conversion_stage: string;
  created_at: string;
}

interface PlatformBreakdown {
  platform: string;
  revenue: number;
  net_revenue: number;
  count: number;
}

interface RevenueSummary {
  total_revenue: number;
  total_net_revenue: number;
  total_fee: number;
  count: number;
  platform_breakdown: PlatformBreakdown[];
  product_breakdown: { product: string; revenue: number; net_revenue: number; count: number }[];
}

const PLATFORM_OPTIONS = [
  { value: "booth", label: "Booth" },
  { value: "note", label: "note" },
  { value: "stripe", label: "Stripe" },
  { value: "gumroad", label: "Gumroad" },
  { value: "membership", label: "Membership" },
  { value: "btob", label: "BtoB" },
  { value: "other", label: "その他" },
];

/** プラットフォーム手数料の自動計算 */
function calcFee(platform: string, revenueJpy: number): number {
  switch (platform) {
    case "booth":
      return Math.round(revenueJpy * 0.056 + 45);
    case "note":
      return Math.round(revenueJpy * 0.15);
    case "stripe":
      return Math.round(revenueJpy * 0.036 + 40);
    case "gumroad":
      return Math.round(revenueJpy * 0.10 + 75);
    default:
      return 0;
  }
}

export default function RevenuePage() {
  const [summary, setSummary] = useState<RevenueSummary | null>(null);
  const [records, setRecords] = useState<RevenueRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [monthlyTarget, setMonthlyTarget] = useState<number | null>(null);
  const [costData, setCostData] = useState<{ monthly_spent_jpy: number; daily_spent_jpy: number }>({ monthly_spent_jpy: 0, daily_spent_jpy: 0 });

  // Form state
  const [platform, setPlatform] = useState("");
  const [productTitle, setProductTitle] = useState("");
  const [revenueJpy, setRevenueJpy] = useState<number | "">("");
  const [feeJpy, setFeeJpy] = useState<number>(0);
  const [notes, setNotes] = useState("");

  const fetchData = useCallback(async () => {
    try {
      const [summaryRes, historyRes, settingsRes, budgetRes] = await Promise.all([
        apiFetch("/api/revenue/summary?days=30").catch(() => null),
        apiFetch("/api/revenue/history?limit=20").catch(() => null),
        apiFetch("/api/settings").catch(() => null),
        apiFetch("/api/budget/status").catch(() => null),
      ]);
      if (summaryRes && summaryRes.ok) {
        const summaryJson = await summaryRes.json();
        setSummary(summaryJson);
        if (summaryJson.monthly_target != null) {
          setMonthlyTarget(summaryJson.monthly_target);
        }
      }
      if (historyRes && historyRes.ok) {
        const data = await historyRes.json();
        setRecords(data.records ?? []);
      }
      if (settingsRes && settingsRes.ok) {
        const settingsJson = await settingsRes.json();
        if (settingsJson.revenue_target != null) {
          setMonthlyTarget(settingsJson.revenue_target);
        } else if (settingsJson.monthly_revenue_target != null) {
          setMonthlyTarget(settingsJson.monthly_revenue_target);
        }
      }
      if (budgetRes && budgetRes.ok) {
        const budgetJson = await budgetRes.json();
        setCostData({
          monthly_spent_jpy: budgetJson.monthly_spent_jpy ?? budgetJson.monthly_used_jpy ?? 0,
          daily_spent_jpy: budgetJson.daily_spent_jpy ?? budgetJson.daily_used_jpy ?? 0,
        });
      }
    } catch {
      setError("収益データの取得に失敗しました");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Auto-calculate fee when platform or revenue changes
  useEffect(() => {
    if (platform && typeof revenueJpy === "number" && revenueJpy > 0) {
      setFeeJpy(calcFee(platform, revenueJpy));
    }
  }, [platform, revenueJpy]);

  const netRevenue = typeof revenueJpy === "number" ? revenueJpy - feeJpy : 0;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!platform || !productTitle || typeof revenueJpy !== "number" || revenueJpy <= 0) return;
    setSubmitting(true);
    try {
      const res = await apiFetch("/api/revenue/record", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          platform,
          product_title: productTitle,
          revenue_jpy: revenueJpy,
          fee_jpy: feeJpy,
          net_revenue_jpy: netRevenue,
          notes,
        }),
      });
      if (res.ok) {
        // Reset form
        setPlatform("");
        setProductTitle("");
        setRevenueJpy("");
        setFeeJpy(0);
        setNotes("");
        // Refresh data
        setLoading(true);
        await fetchData();
      }
    } catch {
      setError("売上の記録に失敗しました");
    } finally {
      setSubmitting(false);
    }
  };

  const monthlyTotal = summary?.total_revenue ?? 0;

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--accent-purple)] border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="flex items-center justify-between rounded-lg bg-[var(--accent-red)]/10 border border-[var(--accent-red)]/30 px-4 py-3">
          <span className="text-sm text-[var(--accent-red)]">{error}</span>
          <button onClick={() => setError(null)} className="min-h-[44px] min-w-[44px] flex items-center justify-center text-[var(--accent-red)]" aria-label="エラーを閉じる">
            <span className="text-lg">&times;</span>
          </button>
        </div>
      )}
      <div className="flex items-center gap-2">
        <DollarSign className="h-6 w-6 text-[var(--accent-purple)]" />
        <h1 className="text-2xl font-bold">収益ダッシュボード</h1>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
            <TrendingUp className="h-4 w-4" />
            月間売上
          </div>
          <p className="mt-1 text-2xl font-bold">
            ¥{(summary?.total_revenue ?? 0).toLocaleString("ja-JP")}
          </p>
        </div>
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
            <ArrowUpRight className="h-4 w-4" />
            月間純収益
          </div>
          <p className="mt-1 text-2xl font-bold text-[var(--accent-green)]">
            ¥{(summary?.total_net_revenue ?? 0).toLocaleString("ja-JP")}
          </p>
        </div>
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
            <ArrowDownRight className="h-4 w-4" />
            月間手数料
          </div>
          <p className="mt-1 text-2xl font-bold text-[var(--text-secondary)]">
            ¥{(summary?.total_fee ?? 0).toLocaleString("ja-JP")}
          </p>
        </div>
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
            <BarChart3 className="h-4 w-4" />
            取引件数
          </div>
          <p className="mt-1 text-2xl font-bold">{summary?.count ?? 0}</p>
        </div>
      </div>

      {/* Revenue Target Progress */}
      <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
        {monthlyTarget != null && monthlyTarget > 0 ? (
          <>
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm font-medium">月間目標: ¥{monthlyTarget.toLocaleString("ja-JP")}</p>
              <p className="text-sm text-[var(--text-secondary)]">{Math.min((monthlyTotal / monthlyTarget) * 100, 100).toFixed(1)}%</p>
            </div>
            <div className="h-3 w-full rounded-full bg-[var(--bg-primary)]">
              <div
                className={`h-3 rounded-full transition-all ${
                  monthlyTotal >= monthlyTarget
                    ? "bg-[var(--accent-green)]"
                    : monthlyTotal >= monthlyTarget * 0.5
                    ? "bg-[var(--accent-purple)]"
                    : "bg-[var(--accent-blue)]"
                }`}
                style={{ width: `${Math.min((monthlyTotal / monthlyTarget) * 100, 100)}%` }}
              />
            </div>
            <p className="mt-2 text-xs text-[var(--text-secondary)]">
              ¥{monthlyTotal.toLocaleString("ja-JP")} / ¥{monthlyTarget.toLocaleString("ja-JP")}
            </p>
          </>
        ) : (
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium">月間売上: ¥{monthlyTotal.toLocaleString("ja-JP")}</p>
            <span className="rounded-full bg-[var(--bg-primary)] px-2.5 py-0.5 text-xs text-[var(--text-secondary)]">目標未設定</span>
          </div>
        )}
      </div>

      {/* Task 5: Cost vs Revenue */}
      <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
        <p className="text-sm font-medium">
          支出 <span className="text-[var(--accent-red)]">¥{costData.monthly_spent_jpy.toLocaleString("ja-JP")}</span>
          {" / "}収益 <span className="text-[var(--accent-green)]">¥{monthlyTotal.toLocaleString("ja-JP")}</span>
          {" = "}損益{" "}
          <span className={monthlyTotal - costData.monthly_spent_jpy >= 0 ? "text-[var(--accent-green)]" : "text-[var(--accent-red)]"}>
            ¥{(monthlyTotal - costData.monthly_spent_jpy).toLocaleString("ja-JP")}
          </span>
        </p>
      </div>

      {/* Manual Revenue Recording Form */}
      <div className="rounded-lg border border-[var(--accent-green)]/30 bg-[var(--bg-card)] p-4">
        <div className="flex items-center gap-2 mb-3">
          <Plus className="h-5 w-5 text-[var(--accent-green)]" />
          <h2 className="text-lg font-semibold">売上を記録</h2>
        </div>
        <form onSubmit={handleSubmit} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <select
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
            required
            className="rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-3 text-base sm:text-sm min-h-[44px]"
          >
            <option value="">プラットフォーム</option>
            {PLATFORM_OPTIONS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
          <input
            value={productTitle}
            onChange={(e) => setProductTitle(e.target.value)}
            required
            placeholder="商品名"
            className="rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-3 text-base sm:text-sm min-h-[44px]"
          />
          <div>
            <input
              value={revenueJpy === "" ? "" : revenueJpy}
              onChange={(e) => {
                const v = e.target.value;
                setRevenueJpy(v === "" ? "" : Number(v));
              }}
              type="number"
              required
              min={1}
              placeholder="売上金額（円）"
              className="w-full rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-3 text-base sm:text-sm min-h-[44px]"
            />
          </div>
          <div className="flex gap-2">
            <div className="flex-1">
              <input
                value={feeJpy}
                onChange={(e) => setFeeJpy(Number(e.target.value))}
                type="number"
                min={0}
                placeholder="手数料（円）"
                className="w-full rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-3 text-base sm:text-sm min-h-[44px]"
              />
              <p className="mt-1 text-xs text-[var(--text-secondary)]">自動計算済み（手動変更可）</p>
            </div>
            <div className="flex-1">
              <input
                value={netRevenue}
                readOnly
                placeholder="純収益"
                className="w-full rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-3 text-base sm:text-sm min-h-[44px] opacity-70"
              />
              <p className="mt-1 text-xs text-[var(--text-secondary)]">純収益（自動）</p>
            </div>
          </div>
          <input
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="メモ（任意）"
            className="rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-3 text-base sm:text-sm min-h-[44px] sm:col-span-2"
          />
          <button
            type="submit"
            disabled={submitting}
            className="col-span-full rounded-md bg-[var(--accent-green)] px-4 py-3 text-base sm:text-sm font-medium text-white hover:bg-[var(--accent-green)]/80 active:bg-[var(--accent-green)]/60 disabled:opacity-50 min-h-[48px]"
          >
            {submitting ? "記録中..." : "売上を記録"}
          </button>
        </form>
      </div>

      {/* Platform Breakdown */}
      {summary && summary.platform_breakdown && summary.platform_breakdown.length > 0 && (
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <h2 className="mb-3 text-lg font-semibold">プラットフォーム別（今月）</h2>
          <div className="space-y-2">
            {summary.platform_breakdown.map((p) => (
              <div
                key={p.platform}
                className="flex flex-col sm:flex-row sm:items-center justify-between rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-3 py-3 gap-1"
              >
                <span className="text-sm font-medium">{p.platform || "不明"}</span>
                <div className="flex items-center gap-3 text-sm">
                  <span className="text-[var(--text-secondary)]">{p.count}件</span>
                  <span className="font-bold">&yen;{p.revenue.toLocaleString("ja-JP")}</span>
                  <span className="text-[var(--accent-green)]">
                    (純 &yen;{p.net_revenue.toLocaleString("ja-JP")})
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Revenue History Table */}
      <div>
        <h2 className="mb-3 text-lg font-semibold">収益履歴</h2>
        <div className="space-y-2">
          {records.map((r) => (
            <div
              key={r.id}
              className="flex items-center justify-between rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] px-4 py-3"
            >
              <div className="flex items-center gap-3">
                <ArrowUpRight className="h-5 w-5 text-[var(--accent-green)]" />
                <div>
                  <p className="font-medium">{r.product_title || "(タイトルなし)"}</p>
                  <p className="text-xs text-[var(--text-secondary)]">
                    {r.platform} &middot; {new Date(r.created_at).toLocaleString("ja-JP")}
                    {r.notes ? ` &middot; ${r.notes}` : ""}
                  </p>
                </div>
              </div>
              <div className="text-right">
                <span className="font-bold text-[var(--accent-green)]">
                  ¥{r.revenue_jpy.toLocaleString("ja-JP")}
                </span>
                {r.fee_jpy > 0 && (
                  <p className="text-xs text-[var(--text-secondary)]">
                    手数料 ¥{r.fee_jpy.toLocaleString("ja-JP")} / 純 ¥{r.net_revenue_jpy.toLocaleString("ja-JP")}
                  </p>
                )}
              </div>
            </div>
          ))}
          {records.length === 0 && (
            <p className="py-12 text-center text-[var(--text-secondary)]">収益データはまだありません</p>
          )}
        </div>
      </div>
    </div>
  );
}
