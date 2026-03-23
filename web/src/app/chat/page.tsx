"use client";

import { useState, useEffect } from "react";
import { Brain, ChevronRight, ChevronLeft } from "lucide-react";
import ChatInterface from "@/components/ChatInterface";
import { apiFetch } from "@/lib/api";

interface PersonaEntry {
  category: string;
  count: number;
}

export default function ChatPage() {
  const [sideOpen, setSideOpen] = useState(false);
  const [personaStats, setPersonaStats] = useState<PersonaEntry[]>([]);
  const [sessionSummary, setSessionSummary] = useState<string>("");
  const [totalMemories, setTotalMemories] = useState(0);

  useEffect(() => {
    if (!sideOpen) return;
    const fetchMemory = async () => {
      try {
        const [pRes, sRes] = await Promise.all([
          apiFetch("/api/brain-alpha/persona-stats"),
          apiFetch("/api/brain-alpha/sessions?limit=1"),
        ]);
        if (pRes.ok) {
          const d = await pRes.json();
          setPersonaStats(d.categories || []);
          setTotalMemories(d.total || 0);
        }
        if (sRes.ok) {
          const d = await sRes.json();
          if (d.sessions?.length > 0) {
            setSessionSummary(d.sessions[0].summary || "");
          }
        }
      } catch {
        // ignore
      }
    };
    fetchMemory();
  }, [sideOpen]);

  const catLabels: Record<string, string> = {
    philosophy: "哲学",
    conversation: "会話",
    approval_pattern: "承認",
    judgment: "判断",
    preference: "好み",
  };

  return (
    <div className="flex gap-4">
      <div className="flex-1 min-w-0">
        <h1 className="mb-4 text-2xl font-bold">チャット</h1>
        <ChatInterface />
      </div>

      {/* サイドパネルトグル */}
      <button
        onClick={() => setSideOpen(!sideOpen)}
        className="fixed right-0 top-1/2 -translate-y-1/2 z-30 flex items-center gap-0.5 rounded-l-lg border border-r-0 border-[var(--border-color)] bg-[var(--bg-card)] px-1 py-3 text-[var(--text-secondary)] hover:text-[var(--accent-purple)] transition-colors md:hidden"
      >
        {sideOpen ? <ChevronRight className="h-4 w-4" /> : <Brain className="h-4 w-4" />}
      </button>

      {/* デスクトップ: 常時トグル可能なサイドパネル */}
      <div className={`${sideOpen ? "w-72" : "w-0"} transition-all duration-200 overflow-hidden flex-shrink-0 hidden md:block`}>
        {sideOpen && (
          <div className="w-72 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1">
                <Brain className="h-4 w-4 text-[var(--accent-purple)]" />
                <span className="text-sm font-semibold">Brain-&alpha;の記憶</span>
              </div>
              <button onClick={() => setSideOpen(false)} className="text-[var(--text-secondary)] hover:text-white">
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>

            {/* 直近セッション */}
            {sessionSummary && (
              <div className="rounded-md border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-2">
                <p className="text-[10px] text-[var(--text-secondary)] mb-1">前回セッション</p>
                <p className="text-xs line-clamp-3">{sessionSummary}</p>
              </div>
            )}

            {/* persona統計 */}
            <div className="rounded-md border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-2">
              <p className="text-[10px] text-[var(--text-secondary)] mb-1">人格記憶 ({totalMemories}件)</p>
              <div className="space-y-1">
                {personaStats.map((p) => (
                  <div key={p.category} className="flex items-center justify-between text-xs">
                    <span>{catLabels[p.category] || p.category}</span>
                    <span className="font-mono text-[var(--accent-purple)]">{p.count}</span>
                  </div>
                ))}
              </div>
            </div>

            <a href="/brain-alpha" className="block text-center text-xs text-[var(--accent-purple)] hover:underline">
              Brain-&alpha;詳細 →
            </a>
          </div>
        )}
      </div>

      {/* モバイル: オーバーレイ */}
      {sideOpen && (
        <div className="fixed inset-0 z-40 md:hidden" onClick={() => setSideOpen(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <div
            className="absolute right-0 top-0 h-full w-72 border-l border-[var(--border-color)] bg-[var(--bg-secondary)] p-4 space-y-3"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1">
                <Brain className="h-4 w-4 text-[var(--accent-purple)]" />
                <span className="text-sm font-semibold">Brain-&alpha;の記憶</span>
              </div>
              <button onClick={() => setSideOpen(false)} className="text-[var(--text-secondary)]">
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
            {sessionSummary && (
              <div className="rounded-md border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-2">
                <p className="text-[10px] text-[var(--text-secondary)] mb-1">前回セッション</p>
                <p className="text-xs line-clamp-3">{sessionSummary}</p>
              </div>
            )}
            <div className="rounded-md border border-[var(--border-color)] bg-[var(--bg-card)] px-3 py-2">
              <p className="text-[10px] text-[var(--text-secondary)] mb-1">人格記憶 ({totalMemories}件)</p>
              <div className="space-y-1">
                {personaStats.map((p) => (
                  <div key={p.category} className="flex items-center justify-between text-xs">
                    <span>{catLabels[p.category] || p.category}</span>
                    <span className="font-mono text-[var(--accent-purple)]">{p.count}</span>
                  </div>
                ))}
              </div>
            </div>
            <a href="/brain-alpha" className="block text-center text-xs text-[var(--accent-purple)] hover:underline">
              Brain-&alpha;詳細 →
            </a>
          </div>
        </div>
      )}

      {/* デスクトップ: 開くボタン（閉じている時） */}
      {!sideOpen && (
        <button
          onClick={() => setSideOpen(true)}
          className="hidden md:flex items-center gap-1 fixed right-4 top-20 z-30 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] px-2 py-1.5 text-xs text-[var(--text-secondary)] hover:text-[var(--accent-purple)] transition-colors"
        >
          <Brain className="h-3 w-3" />
          <ChevronLeft className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}
