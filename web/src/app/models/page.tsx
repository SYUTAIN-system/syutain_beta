"use client";

import { useEffect, useState } from "react";
import { Cpu, Zap, Server, CircleDollarSign, Scale } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface BudgetStatus {
  daily_used_jpy: number;
  daily_limit_jpy: number;
  monthly_used_jpy: number;
  monthly_limit_jpy: number;
  daily_percent: number;
  monthly_percent: number;
}

interface ModelUsageEntry {
  model: string;
  provider: string;
  calls: number;
  total_tokens: number;
  cost_jpy: number;
  is_local: boolean;
}

export default function ModelsPage() {
  const [budget, setBudget] = useState<BudgetStatus | null>(null);
  const [usage, setUsage] = useState<ModelUsageEntry[]>([]);
  const [loading, setLoading] = useState(true);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [crossEvals, setCrossEvals] = useState<any[]>([]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [budgetRes, usageRes, evalRes] = await Promise.all([
          apiFetch("/api/budget/status").catch(() => null),
          apiFetch("/api/model-usage").catch(() => null),
          apiFetch("/api/brain-alpha/cross-evaluations?limit=10").catch(() => null),
        ]);

        if (budgetRes && budgetRes.ok) {
          const json = await budgetRes.json();
          setBudget({
            daily_used_jpy: json.daily_used_jpy ?? 0,
            daily_limit_jpy: json.daily_limit_jpy ?? 80,
            monthly_used_jpy: json.monthly_used_jpy ?? 0,
            monthly_limit_jpy: json.monthly_limit_jpy ?? 1500,
            daily_percent: json.daily_percent ?? 0,
            monthly_percent: json.monthly_percent ?? 0,
          });
        } else {
          setBudget({
            daily_used_jpy: 0,
            daily_limit_jpy: 80,
            monthly_used_jpy: 0,
            monthly_limit_jpy: 1500,
            daily_percent: 0,
            monthly_percent: 0,
          });
        }

        if (evalRes && evalRes.ok) {
          const ej = await evalRes.json();
          setCrossEvals(ej.evaluations || []);
        }

        if (usageRes && usageRes.ok) {
          const json = await usageRes.json();
          const list = json.usage ?? json.models ?? json;
          if (Array.isArray(list)) {
            // APIフィールドをフロントエンド型にマッピング
            const mapped: ModelUsageEntry[] = list.map((item: Record<string, unknown>) => ({
              model: String(item.model ?? item.model_used ?? "unknown"),
              provider: String(item.provider ?? (item.tier === "L" ? "ローカル" : item.tier === "S" ? "Google" : "DeepSeek")),
              calls: Number(item.calls ?? item.call_count ?? 0),
              total_tokens: Number(item.total_tokens ?? 0),
              cost_jpy: Number(item.cost_jpy ?? item.total_cost ?? 0),
              is_local: Boolean(item.is_local ?? item.tier === "L"),
            }));
            setUsage(mapped);
          }
        }
      } catch {
        setBudget({
          daily_used_jpy: 0,
          daily_limit_jpy: 80,
          monthly_used_jpy: 0,
          monthly_limit_jpy: 1500,
          daily_percent: 0,
          monthly_percent: 0,
        });
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--accent-purple)] border-t-transparent" />
      </div>
    );
  }

  const b = budget!;
  const dailyPercent = b.daily_limit_jpy > 0 ? Math.min((b.daily_used_jpy / b.daily_limit_jpy) * 100, 100) : 0;
  const monthlyPercent = b.monthly_limit_jpy > 0 ? Math.min((b.monthly_used_jpy / b.monthly_limit_jpy) * 100, 100) : 0;

  const localCalls = usage.filter((u) => u.is_local).reduce((s, u) => s + u.calls, 0);
  const apiCalls = usage.filter((u) => !u.is_local).reduce((s, u) => s + u.calls, 0);
  const totalCalls = localCalls + apiCalls;
  const localRatio = totalCalls > 0 ? ((localCalls / totalCalls) * 100).toFixed(1) : "0.0";
  const apiRatio = totalCalls > 0 ? ((apiCalls / totalCalls) * 100).toFixed(1) : "0.0";

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Cpu className="h-6 w-6 text-[var(--accent-purple)]" />
        <h1 className="text-2xl font-bold">モデル使用状況</h1>
      </div>

      {/* Budget Progress */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
              <CircleDollarSign className="h-4 w-4" />
              日次API予算
            </div>
            <p className="text-sm text-[var(--text-secondary)]">{dailyPercent.toFixed(1)}%</p>
          </div>
          <p className="text-xl font-bold mb-2">
            ¥{b.daily_used_jpy.toLocaleString("ja-JP")} / ¥{b.daily_limit_jpy.toLocaleString("ja-JP")}
          </p>
          <div className="h-2.5 w-full rounded-full bg-[var(--bg-primary)]">
            <div
              className={`h-2.5 rounded-full transition-all ${
                dailyPercent > 80 ? "bg-[var(--accent-red)]" : dailyPercent > 50 ? "bg-yellow-500" : "bg-[var(--accent-green)]"
              }`}
              style={{ width: `${dailyPercent}%` }}
            />
          </div>
        </div>
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
              <CircleDollarSign className="h-4 w-4" />
              月次API予算
            </div>
            <p className="text-sm text-[var(--text-secondary)]">{monthlyPercent.toFixed(1)}%</p>
          </div>
          <p className="text-xl font-bold mb-2">
            ¥{b.monthly_used_jpy.toLocaleString("ja-JP")} / ¥{b.monthly_limit_jpy.toLocaleString("ja-JP")}
          </p>
          <div className="h-2.5 w-full rounded-full bg-[var(--bg-primary)]">
            <div
              className={`h-2.5 rounded-full transition-all ${
                monthlyPercent > 80 ? "bg-[var(--accent-red)]" : monthlyPercent > 50 ? "bg-yellow-500" : "bg-[var(--accent-green)]"
              }`}
              style={{ width: `${monthlyPercent}%` }}
            />
          </div>
        </div>
      </div>

      {/* Local vs API Ratio */}
      <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
        <h2 className="mb-3 text-lg font-semibold">ローカルLLM vs API 使用比率</h2>
        <div className="grid grid-cols-2 gap-4">
          <div className="flex items-center gap-3">
            <Server className="h-5 w-5 text-[var(--accent-green)]" />
            <div>
              <p className="text-sm text-[var(--text-secondary)]">ローカルLLM</p>
              <p className="text-lg font-bold">{localCalls.toLocaleString()} 回 ({localRatio}%)</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Zap className="h-5 w-5 text-[var(--accent-blue)]" />
            <div>
              <p className="text-sm text-[var(--text-secondary)]">外部API</p>
              <p className="text-lg font-bold">{apiCalls.toLocaleString()} 回 ({apiRatio}%)</p>
            </div>
          </div>
        </div>
        {totalCalls > 0 && (
          <div className="mt-3 flex h-3 w-full overflow-hidden rounded-full bg-[var(--bg-primary)]">
            <div
              className="h-3 bg-[var(--accent-green)] transition-all"
              style={{ width: `${localRatio}%` }}
            />
            <div
              className="h-3 bg-[var(--accent-blue)] transition-all"
              style={{ width: `${apiRatio}%` }}
            />
          </div>
        )}
        {totalCalls === 0 && (
          <p className="mt-3 text-sm text-[var(--text-secondary)]">使用データはまだありません</p>
        )}
      </div>

      {/* Model Usage Table */}
      <div>
        <h2 className="mb-3 text-lg font-semibold">モデル別使用量</h2>
        {usage.length > 0 ? (
          <div className="overflow-x-auto rounded-lg border border-[var(--border-color)]">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border-color)] bg-[var(--bg-card)]">
                  <th className="px-4 py-3 text-left font-medium text-[var(--text-secondary)]">モデル</th>
                  <th className="px-4 py-3 text-left font-medium text-[var(--text-secondary)]">プロバイダ</th>
                  <th className="px-4 py-3 text-right font-medium text-[var(--text-secondary)]">呼出回数</th>
                  <th className="px-4 py-3 text-right font-medium text-[var(--text-secondary)]">Tier</th>
                  <th className="px-4 py-3 text-right font-medium text-[var(--text-secondary)]">コスト</th>
                </tr>
              </thead>
              <tbody>
                {usage.map((u, i) => (
                  <tr
                    key={`${u.model}-${i}`}
                    className="border-b border-[var(--border-color)] bg-[var(--bg-card)] last:border-b-0"
                  >
                    <td className="px-4 py-3 font-medium">
                      {u.model}
                      {u.is_local && (
                        <span className="ml-2 rounded-full bg-[var(--accent-green)]/10 px-2 py-0.5 text-xs text-[var(--accent-green)]">
                          ローカル
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[var(--text-secondary)]">{u.provider}</td>
                    <td className="px-4 py-3 text-right">{u.calls.toLocaleString()}</td>
                    <td className="px-4 py-3 text-right text-[var(--text-secondary)]">{u.is_local ? "L (ローカル)" : "A (API)"}</td>
                    <td className="px-4 py-3 text-right font-medium">¥{u.cost_jpy.toLocaleString("ja-JP")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="py-12 text-center text-[var(--text-secondary)]">モデル使用データはまだありません</p>
        )}
      </div>

      {/* Brain-α品質修正履歴 */}
      {crossEvals.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Scale className="h-5 w-5 text-[var(--accent-purple)]" />
            <h2 className="text-lg font-semibold">Brain-&alpha; 品質修正検証</h2>
          </div>
          <div className="space-y-2">
            {crossEvals.map((ev: {id: number; target_type: string; score: number; evaluation: string; recommendations: Record<string, unknown>; created_at: string}) => {
              const s = ev.score ?? 0;
              const color = s >= 0.7 ? "text-[var(--accent-green)]" : s >= 0.4 ? "text-[var(--accent-amber)]" : "text-[var(--accent-red)]";
              return (
                <div key={ev.id} className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] px-4 py-3">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-medium">{ev.target_type}</span>
                    <span className={`text-sm font-bold ${color}`}>{(s * 100).toFixed(0)}%</span>
                  </div>
                  <p className="text-xs text-[var(--text-secondary)]">{ev.evaluation}</p>
                  {ev.recommendations && (
                    <div className="mt-1 flex gap-3 text-[10px] text-[var(--text-secondary)]">
                      {ev.recommendations.quality_improvement != null && (
                        <span>品質変化: {Number(ev.recommendations.quality_improvement) >= 0 ? "+" : ""}{Number(ev.recommendations.quality_improvement).toFixed(3)}</span>
                      )}
                      {ev.recommendations.error_improvement != null && (
                        <span>エラー変化: {Number(ev.recommendations.error_improvement) >= 0 ? "-" : "+"}{Math.abs(Number(ev.recommendations.error_improvement))}</span>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
