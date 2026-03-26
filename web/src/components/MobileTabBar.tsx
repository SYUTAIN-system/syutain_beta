"use client";

import { usePathname } from "next/navigation";
import { useState, useEffect, useRef } from "react";
import {
  LayoutDashboard,
  MessageCircle,
  ListChecks,
  FileStack,
  FileText,
  MoreHorizontal,
  Bot,
  Brain,
  Server,
  DollarSign,
  Cpu,
  Search,
  Settings,
} from "lucide-react";

const mainTabs = [
  { href: "/", label: "ホーム", icon: LayoutDashboard },
  { href: "/chat", label: "チャット", icon: MessageCircle },
  { href: "/tasks", label: "タスク", icon: ListChecks },
  { href: "/proposals", label: "提案", icon: FileStack },
];

const moreTabs = [
  { href: "/artifacts", label: "成果物", icon: FileText },
  { href: "/agent-ops", label: "Agent Ops", icon: Bot },
  { href: "/brain-alpha", label: "Brain-α", icon: Brain },
  { href: "/node-control", label: "ノード", icon: Server },
  { href: "/revenue", label: "収益", icon: DollarSign },
  { href: "/models", label: "モデル", icon: Cpu },
  { href: "/intel", label: "情報収集", icon: Search },
  { href: "/settings", label: "設定", icon: Settings },
];

export default function MobileTabBar() {
  const pathname = usePathname();
  const [moreOpen, setMoreOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // 外側タップで閉じる
  useEffect(() => {
    if (!moreOpen) return;
    const handleClick = (e: Event) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMoreOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("touchstart", handleClick);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("touchstart", handleClick);
    };
  }, [moreOpen]);

  // ページ遷移で閉じる
  useEffect(() => {
    setMoreOpen(false);
  }, [pathname]);

  const isMoreActive = moreTabs.some((t) => pathname.startsWith(t.href));

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 border-t border-[var(--border-color)] bg-[var(--bg-secondary)]/95 backdrop-blur-md md:hidden">
      {/* その他メニュー（ボトムシート） */}
      {moreOpen && (
        <div ref={menuRef} className="border-t border-[var(--border-color)] bg-[var(--bg-card)] px-4 pb-2 pt-3">
          <div className="grid grid-cols-5 gap-1">
            {moreTabs.map((tab) => {
              const isActive = pathname.startsWith(tab.href);
              const Icon = tab.icon;
              return (
                <a
                  key={tab.href}
                  href={tab.href}
                  className={`flex flex-col items-center justify-center gap-1 rounded-lg py-2.5 transition-colors ${
                    isActive
                      ? "bg-[var(--accent-purple)]/10 text-[var(--accent-purple)]"
                      : "text-[var(--text-secondary)] hover:text-white"
                  }`}
                >
                  <Icon className="h-5 w-5" />
                  <span className="text-[10px] leading-tight">{tab.label}</span>
                </a>
              );
            })}
          </div>
        </div>
      )}

      {/* メインタブバー */}
      <div className="flex items-stretch justify-around">
        {mainTabs.map((tab) => {
          const isActive = tab.href === "/" ? pathname === "/" : pathname.startsWith(tab.href);
          const Icon = tab.icon;
          return (
            <a
              key={tab.href}
              href={tab.href}
              className={`flex min-h-[56px] min-w-[44px] flex-1 flex-col items-center justify-center gap-0.5 px-1 py-2 transition-colors ${
                isActive
                  ? "text-[var(--accent-purple)]"
                  : "text-[var(--text-secondary)]"
              }`}
            >
              <Icon className="h-5 w-5" />
              <span className="text-[10px] leading-tight">{tab.label}</span>
            </a>
          );
        })}
        {/* その他ボタン */}
        <button
          onClick={() => setMoreOpen(!moreOpen)}
          className={`flex min-h-[56px] min-w-[44px] flex-1 flex-col items-center justify-center gap-0.5 px-1 py-2 transition-colors ${
            isMoreActive || moreOpen
              ? "text-[var(--accent-purple)]"
              : "text-[var(--text-secondary)]"
          }`}
        >
          <MoreHorizontal className="h-5 w-5" />
          <span className="text-[10px] leading-tight">その他</span>
        </button>
      </div>
      {/* Safe area for iPhone home indicator */}
      <div className="h-[env(safe-area-inset-bottom)]" />
    </nav>
  );
}
