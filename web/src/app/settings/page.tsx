"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Settings,
  ToggleLeft,
  ToggleRight,
  CircleDollarSign,
  Server,
  ChevronDown,
  ChevronUp,
  MessageSquare,
  Bell,
  CheckCircle,
  AlertCircle,
  Save,
} from "lucide-react";
import { apiFetch } from "@/lib/api";

/* ── Types ── */

interface FeatureFlag {
  key: string;
  enabled: boolean;
  description?: string;
}

interface BudgetSettings {
  daily_limit_jpy: number;
  monthly_limit_jpy: number;
  chat_daily_limit_jpy: number;
}

interface BudgetUsage {
  daily_used_jpy: number;
  monthly_used_jpy: number;
  chat_daily_used_jpy: number;
}

interface DiscordNotifications {
  goal_accepted: boolean;
  task_completed: boolean;
  error_alert: boolean;
  node_status: boolean;
  proposal_created: boolean;
}

type ChatModel = "auto" | "local" | "deepseek" | "gemini_flash" | "claude_sonnet";

interface NodeConfig {
  name: string;
  model: string;
  role: string;
  browser_layer: boolean;
}

/* ── Constants ── */

const DEFAULT_NODES: NodeConfig[] = [
  { name: "ALPHA", model: "推論なし（Brain-α専用）", role: "Brain-α + Brain-βインフラ", browser_layer: false },
  { name: "BRAVO", model: "Nemotron 9B JP + Qwen3.5-9B", role: "LLM主力 + ブラウザ操作", browser_layer: true },
  { name: "CHARLIE", model: "Nemotron 9B JP + Qwen3.5-9B", role: "副推論 + コンテンツ生成（ブラウザ操作なし）", browser_layer: false },
  { name: "DELTA", model: "Qwen3.5-4B", role: "監視 + 軽量タスク", browser_layer: false },
];

const CHAT_MODEL_OPTIONS: { value: ChatModel; label: string; description: string }[] = [
  { value: "auto", label: "自動（推奨）", description: "タスクに応じて最適なモデルを自動選択" },
  { value: "local", label: "ローカルLLM", description: "Qwen3.5 ローカル推論" },
  { value: "deepseek", label: "DeepSeek", description: "DeepSeek API" },
  { value: "gemini_flash", label: "Gemini Flash", description: "Google Gemini Flash API" },
  { value: "claude_sonnet", label: "Claude Sonnet", description: "Anthropic Claude Sonnet API" },
];

/* ── Toast Component ── */

function Toast({ message, type, onClose }: { message: string; type: "success" | "error"; onClose: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onClose, 3000);
    return () => clearTimeout(timer);
  }, [onClose]);

  return (
    <div
      className="fixed top-4 right-4 z-50 flex items-center gap-2 rounded-lg px-4 py-3 shadow-lg transition-all"
      style={{
        backgroundColor: type === "success" ? "var(--accent-green)" : "var(--accent-red)",
        color: "#fff",
        animation: "toast-in 0.3s ease-out",
      }}
    >
      {type === "success" ? (
        <CheckCircle className="h-4 w-4 flex-shrink-0" />
      ) : (
        <AlertCircle className="h-4 w-4 flex-shrink-0" />
      )}
      <span className="text-sm font-medium">{message}</span>
    </div>
  );
}

/* ── Progress Bar ── */

function ProgressBar({ used, limit, label }: { used: number; limit: number; label: string }) {
  const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0;
  const color = pct >= 90 ? "var(--accent-red)" : pct >= 70 ? "var(--accent-amber)" : "var(--accent-green)";

  return (
    <div className="mt-2">
      <div className="flex items-center justify-between text-xs text-[var(--text-secondary)] mb-1">
        <span>{label}</span>
        <span>
          ¥{used.toLocaleString("ja-JP")} / ¥{limit.toLocaleString("ja-JP")} ({pct.toFixed(0)}%)
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-[var(--bg-primary)] overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}

/* ── Slider + Number Input ── */

function SliderInput({
  value,
  onChange,
  min,
  max,
  step,
  label,
  unit,
}: {
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step: number;
  label: string;
  unit?: string;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium">{label}</label>
        <div className="flex items-center gap-1">
          {unit && <span className="text-sm text-[var(--text-secondary)]">{unit}</span>}
          <input
            type="number"
            min={min}
            max={max}
            step={step}
            value={value}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (v >= min && v <= max) onChange(v);
            }}
            className="w-24 rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-2 py-2 text-right text-base sm:text-sm min-h-[44px] focus:outline-none focus:ring-1 focus:ring-[var(--accent-purple)]"
          />
        </div>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-[var(--accent-purple)] cursor-pointer h-6 sm:h-auto"
      />
      <div className="flex justify-between text-xs text-[var(--text-secondary)]">
        <span>¥{min.toLocaleString("ja-JP")}</span>
        <span>¥{max.toLocaleString("ja-JP")}</span>
      </div>
    </div>
  );
}

/* ── Toggle Switch ── */

function ToggleSwitch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="flex w-full items-center justify-between rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-4 py-4 sm:py-3 transition-colors hover:border-[var(--accent-purple)] active:bg-[var(--bg-card)] min-h-[48px]"
    >
      <span className="text-sm font-medium">{label}</span>
      <div className="flex items-center gap-2">
        {checked ? (
          <ToggleRight className="h-6 w-6 text-[var(--accent-green)]" />
        ) : (
          <ToggleLeft className="h-6 w-6 text-[var(--text-secondary)]" />
        )}
        <span
          className={`text-xs font-medium ${
            checked ? "text-[var(--accent-green)]" : "text-[var(--text-secondary)]"
          }`}
        >
          {checked ? "ON" : "OFF"}
        </span>
      </div>
    </button>
  );
}

/* ── Save Button ── */

function SaveButton({ onClick, saving }: { onClick: () => void; saving: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={saving}
      className="mt-4 flex w-full sm:w-auto items-center justify-center gap-2 rounded-lg bg-[var(--accent-purple)] px-6 py-3 text-base sm:text-sm font-medium text-white transition-opacity hover:opacity-90 active:opacity-70 disabled:opacity-50 min-h-[48px]"
    >
      <Save className="h-4 w-4" />
      {saving ? "保存中..." : "保存"}
    </button>
  );
}

/* ── Main Page ── */

export default function SettingsPage() {
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);

  // Budget state
  const [budgetOpen, setBudgetOpen] = useState(true);
  const [budget, setBudget] = useState<BudgetSettings>({
    daily_limit_jpy: 80,
    monthly_limit_jpy: 1500,
    chat_daily_limit_jpy: 30,
  });
  const [usage, setUsage] = useState<BudgetUsage>({
    daily_used_jpy: 0,
    monthly_used_jpy: 0,
    chat_daily_used_jpy: 0,
  });
  const [savingBudget, setSavingBudget] = useState(false);

  // Chat model state
  const [chatModel, setChatModel] = useState<ChatModel>("auto");
  const [savingModel, setSavingModel] = useState(false);

  // Discord notification state
  const [discord, setDiscord] = useState<DiscordNotifications>({
    goal_accepted: true,
    task_completed: true,
    error_alert: true,
    node_status: false,
    proposal_created: true,
  });
  const [savingDiscord, setSavingDiscord] = useState(false);

  // Feature flags & nodes (read-only)
  const [flags, setFlags] = useState<FeatureFlag[]>([]);

  // Brain-α status from API
  const [brainStatus, setBrainStatus] = useState<Record<string, string>>({});

  const showToast = useCallback((message: string, type: "success" | "error") => {
    setToast({ message, type });
  }, []);

  /* ── Fetch initial data ── */
  useEffect(() => {
    const fetchData = async () => {
      try {
        const [settingsRes, budgetRes, brainRes] = await Promise.all([
          apiFetch("/api/settings").catch(() => null),
          apiFetch("/api/budget/status").catch(() => null),
          apiFetch("/api/brain-alpha/latest-report").catch(() => null),
        ]);

        if (settingsRes && settingsRes.ok) {
          const json = await settingsRes.json();
          if (json.budget) {
            setBudget({
              daily_limit_jpy: json.budget.daily_limit_jpy ?? 80,
              monthly_limit_jpy: json.budget.monthly_limit_jpy ?? 1500,
              chat_daily_limit_jpy: json.budget.chat_daily_limit_jpy ?? 30,
            });
          }
          if (json.chat_model) {
            setChatModel(json.chat_model);
          }
          if (json.discord) {
            setDiscord((prev) => ({ ...prev, ...json.discord }));
          }
          if (json.flags) {
            if (Array.isArray(json.flags)) {
              setFlags(json.flags);
            } else if (typeof json.flags === "object") {
              // Handle flat object format: { "flag_name": true, ... }
              const parsed: FeatureFlag[] = Object.entries(json.flags).map(([key, val]) => ({
                key,
                enabled: Boolean(val),
              }));
              setFlags(parsed);
            }
          }
        }

        if (budgetRes && budgetRes.ok) {
          const json = await budgetRes.json();
          setUsage({
            daily_used_jpy: json.daily_used_jpy ?? 0,
            monthly_used_jpy: json.monthly_used_jpy ?? 0,
            chat_daily_used_jpy: json.chat_daily_used_jpy ?? 0,
          });
          // Also update limits if returned from budget endpoint
          if (json.daily_limit_jpy) {
            setBudget((prev) => ({
              ...prev,
              daily_limit_jpy: json.daily_limit_jpy ?? prev.daily_limit_jpy,
              monthly_limit_jpy: json.monthly_limit_jpy ?? prev.monthly_limit_jpy,
              chat_daily_limit_jpy: json.chat_daily_limit_jpy ?? prev.chat_daily_limit_jpy,
            }));
          }
        }
        if (brainRes && brainRes.ok) {
          const brJson = await brainRes.json();
          const report = brJson.report;
          const status: Record<string, string> = {};
          if (report) {
            // Derive status from report phases
            status.channels = "running";
            status.scrutiny = report.phases ? "running" : "preparing";
            status.self_healing = report.phases?.["6_errors"] ? "running" : "preparing";
            status.persona = report.phases?.["1_session_restore"] ? "running" : "running";
          }
          if (brJson.brain_alpha_status) {
            Object.assign(status, brJson.brain_alpha_status);
          }
          setBrainStatus(status);
        }
      } catch {
        // graceful fallback - use defaults
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  /* ── Save handlers ── */

  const saveBudget = async () => {
    setSavingBudget(true);
    try {
      const res = await apiFetch("/api/settings/budget", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          daily_budget_jpy: budget.daily_limit_jpy,
          monthly_budget_jpy: budget.monthly_limit_jpy,
          chat_budget_jpy: budget.chat_daily_limit_jpy,
        }),
      });
      if (res.ok) {
        showToast("予算設定を保存しました", "success");
      } else {
        showToast("予算設定の保存に失敗しました", "error");
      }
    } catch {
      showToast("予算設定の保存に失敗しました", "error");
    } finally {
      setSavingBudget(false);
    }
  };

  const saveChatModel = async () => {
    setSavingModel(true);
    try {
      const res = await apiFetch("/api/settings/chat-model", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: chatModel }),
      });
      if (res.ok) {
        showToast("チャットモデルを保存しました", "success");
      } else {
        showToast("チャットモデルの保存に失敗しました", "error");
      }
    } catch {
      showToast("チャットモデルの保存に失敗しました", "error");
    } finally {
      setSavingModel(false);
    }
  };

  const saveDiscord = async () => {
    setSavingDiscord(true);
    try {
      const res = await apiFetch("/api/settings/discord", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(discord),
      });
      if (res.ok) {
        showToast("Discord通知設定を保存しました", "success");
      } else {
        showToast("Discord通知設定の保存に失敗しました", "error");
      }
    } catch {
      showToast("Discord通知設定の保存に失敗しました", "error");
    } finally {
      setSavingDiscord(false);
    }
  };

  /* ── Loading ── */

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--accent-purple)] border-t-transparent" />
      </div>
    );
  }

  return (
    <>
      {/* Toast */}
      {toast && (
        <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />
      )}

      <style jsx global>{`
        @keyframes toast-in {
          from {
            opacity: 0;
            transform: translateY(-12px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
      `}</style>

      <div className="space-y-6 pb-8">
        {/* Page Header */}
        <div className="flex items-center gap-2">
          <Settings className="h-6 w-6 text-[var(--accent-purple)]" />
          <h1 className="text-2xl font-bold">設定</h1>
        </div>

        {/* ───── 1. API Budget Settings (Accordion) ───── */}
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] overflow-hidden">
          <button
            type="button"
            onClick={() => setBudgetOpen((p) => !p)}
            className="flex w-full items-center justify-between px-4 py-4 transition-colors hover:bg-[var(--bg-primary)]"
          >
            <div className="flex items-center gap-2">
              <CircleDollarSign className="h-5 w-5 text-[var(--accent-purple)]" />
              <h2 className="text-lg font-semibold">API予算設定</h2>
            </div>
            {budgetOpen ? (
              <ChevronUp className="h-5 w-5 text-[var(--text-secondary)]" />
            ) : (
              <ChevronDown className="h-5 w-5 text-[var(--text-secondary)]" />
            )}
          </button>

          {budgetOpen && (
            <div className="border-t border-[var(--border-color)] px-4 pb-4 pt-4 space-y-6">
              <SliderInput
                label="日次API予算"
                unit="¥"
                value={budget.daily_limit_jpy}
                onChange={(v) => setBudget((p) => ({ ...p, daily_limit_jpy: v }))}
                min={10}
                max={500}
                step={10}
              />
              <ProgressBar
                used={usage.daily_used_jpy}
                limit={budget.daily_limit_jpy}
                label="本日の使用量"
              />

              <hr className="border-[var(--border-color)]" />

              <SliderInput
                label="月次API予算"
                unit="¥"
                value={budget.monthly_limit_jpy}
                onChange={(v) => setBudget((p) => ({ ...p, monthly_limit_jpy: v }))}
                min={100}
                max={5000}
                step={100}
              />
              <ProgressBar
                used={usage.monthly_used_jpy}
                limit={budget.monthly_limit_jpy}
                label="今月の使用量"
              />

              <hr className="border-[var(--border-color)]" />

              <SliderInput
                label="チャット予算（日次）"
                unit="¥"
                value={budget.chat_daily_limit_jpy}
                onChange={(v) => setBudget((p) => ({ ...p, chat_daily_limit_jpy: v }))}
                min={5}
                max={100}
                step={5}
              />
              <ProgressBar
                used={usage.chat_daily_used_jpy}
                limit={budget.chat_daily_limit_jpy}
                label="本日のチャット使用量"
              />

              <SaveButton onClick={saveBudget} saving={savingBudget} />
            </div>
          )}
        </div>

        {/* ───── 2. Chat Model Selection ───── */}
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2 mb-4">
            <MessageSquare className="h-5 w-5 text-[var(--accent-purple)]" />
            <h2 className="text-lg font-semibold">チャットモデル選択</h2>
          </div>

          <div className="space-y-2">
            {CHAT_MODEL_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className={`flex cursor-pointer items-center gap-3 rounded-md border px-4 py-4 sm:py-3 min-h-[48px] transition-colors ${
                  chatModel === opt.value
                    ? "border-[var(--accent-purple)] bg-[var(--accent-purple)]/10"
                    : "border-[var(--border-color)] bg-[var(--bg-primary)] hover:border-[var(--accent-purple)]/50"
                }`}
              >
                <input
                  type="radio"
                  name="chatModel"
                  value={opt.value}
                  checked={chatModel === opt.value}
                  onChange={() => setChatModel(opt.value)}
                  className="accent-[var(--accent-purple)]"
                />
                <div>
                  <p className="text-sm font-medium">{opt.label}</p>
                  <p className="text-xs text-[var(--text-secondary)]">{opt.description}</p>
                </div>
              </label>
            ))}
          </div>

          <SaveButton onClick={saveChatModel} saving={savingModel} />
        </div>

        {/* ───── 3. Discord Notification Settings ───── */}
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <div className="flex items-center gap-2 mb-4">
            <Bell className="h-5 w-5 text-[var(--accent-purple)]" />
            <h2 className="text-lg font-semibold">Discord通知設定</h2>
          </div>

          <div className="space-y-2">
            <ToggleSwitch
              label="ゴール受付"
              checked={discord.goal_accepted}
              onChange={(v) => setDiscord((p) => ({ ...p, goal_accepted: v }))}
            />
            <ToggleSwitch
              label="タスク完了"
              checked={discord.task_completed}
              onChange={(v) => setDiscord((p) => ({ ...p, task_completed: v }))}
            />
            <ToggleSwitch
              label="エラー通知"
              checked={discord.error_alert}
              onChange={(v) => setDiscord((p) => ({ ...p, error_alert: v }))}
            />
            <ToggleSwitch
              label="ノード状態"
              checked={discord.node_status}
              onChange={(v) => setDiscord((p) => ({ ...p, node_status: v }))}
            />
            <ToggleSwitch
              label="提案作成"
              checked={discord.proposal_created}
              onChange={(v) => setDiscord((p) => ({ ...p, proposal_created: v }))}
            />
          </div>

          <SaveButton onClick={saveDiscord} saving={savingDiscord} />
        </div>

        {/* ───── 4. System Information (read-only) ───── */}
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] p-4">
          <h2 className="mb-4 text-lg font-semibold">システム情報</h2>

          {/* Feature Flags */}
          <h3 className="mb-2 text-sm font-medium text-[var(--text-secondary)] uppercase tracking-wide">
            機能フラグ
          </h3>
          {flags.length > 0 ? (
            <div className="space-y-2 mb-6">
              {flags.map((flag) => (
                <div
                  key={flag.key}
                  className="flex items-center justify-between rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-4 py-3"
                >
                  <div>
                    <p className="font-medium text-sm">{flag.key}</p>
                    {flag.description && (
                      <p className="text-xs text-[var(--text-secondary)]">{flag.description}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {flag.enabled ? (
                      <ToggleRight className="h-6 w-6 text-[var(--accent-green)]" />
                    ) : (
                      <ToggleLeft className="h-6 w-6 text-[var(--text-secondary)]" />
                    )}
                    <span
                      className={`text-xs font-medium ${
                        flag.enabled ? "text-[var(--accent-green)]" : "text-[var(--text-secondary)]"
                      }`}
                    >
                      {flag.enabled ? "有効" : "無効"}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="mb-6 py-4 text-center text-sm text-[var(--text-secondary)]">
              機能フラグはまだ設定されていません
            </p>
          )}

          {/* Brain-α Configuration */}
          <div className="flex items-center gap-2 mb-2 mt-6">
            <Settings className="h-4 w-4 text-[var(--accent-purple)]" />
            <h3 className="text-sm font-medium text-[var(--text-secondary)] uppercase tracking-wide">
              Brain-&alpha; 設定
            </h3>
          </div>
          <div className="space-y-3">
            {[
              { key: "channels", label: "Channels（Discord Bot）", desc: "tmux brain_alpha セッションで永続稼働" },
              { key: "scrutiny", label: "精査サイクル", desc: "情報収集・成果物・タスク結果の自動精査" },
              { key: "self_healing", label: "自律修復", desc: "エラー検出→原因特定→コード修正の自動化" },
              { key: "persona", label: "人格保持", desc: "persona_memory + daichi_dialogue_log" },
            ].map((item) => {
              const st = brainStatus[item.key] ?? "unknown";
              const isRunning = st === "running" || st === "active" || st === "enabled";
              const statusLabel = isRunning ? "稼働中" : st === "preparing" ? "準備中" : st === "disabled" ? "無効" : "準備中";
              const statusColor = isRunning ? "accent-green" : "accent-amber";
              return (
                <div key={item.key} className="rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-4 py-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium">{item.label}</p>
                      <p className="text-xs text-[var(--text-secondary)]">{item.desc}</p>
                    </div>
                    <span className={`rounded-full bg-[var(--${statusColor})]/10 px-2 py-0.5 text-xs text-[var(--${statusColor})]`}>{statusLabel}</span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Node Configuration */}
          <div className="flex items-center gap-2 mb-2 mt-6">
            <Server className="h-4 w-4 text-[var(--accent-purple)]" />
            <h3 className="text-sm font-medium text-[var(--text-secondary)] uppercase tracking-wide">
              ノード構成
            </h3>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {DEFAULT_NODES.map((node) => (
              <div
                key={node.name}
                className="rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] px-4 py-3"
              >
                <div className="flex items-center justify-between">
                  <p className="font-bold text-[var(--accent-purple)]">{node.name}</p>
                  {node.browser_layer && (
                    <span className="rounded-full bg-[var(--accent-purple)]/10 px-2 py-0.5 text-xs text-[var(--accent-purple)]">
                      Browser
                    </span>
                  )}
                </div>
                <p className="mt-1 text-sm">{node.model}</p>
                <p className="text-xs text-[var(--text-secondary)]">{node.role}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
