"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Send, CheckCircle, XCircle, RefreshCw, Target } from "lucide-react";
import { apiFetch } from "@/lib/api";

interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
  approval_required?: boolean;
  approval_id?: string;
  model_used?: string;
  action?: string;
}

const TYPING_INDICATOR_ID = "__typing_indicator__";

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      role: "system",
      content: "SYUTAINβ に接続しました。ゴールを入力してください。",
      timestamp: new Date().toISOString(),
    },
  ]);
  const [input, setInput] = useState("");
  const [connected, setConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [chatBudget, setChatBudget] = useState({ spent: 0, limit: 30 });
  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const historyLoadedRef = useRef(false);

  // チャット履歴をPostgreSQLから読み込む
  const loadHistory = useCallback(async () => {
    if (historyLoadedRef.current) return;
    historyLoadedRef.current = true;
    try {
      const [historyRes, budgetRes] = await Promise.all([
        apiFetch("/api/chat/history?session_id=default&limit=50"),
        apiFetch("/api/budget/status").catch(() => null),
      ]);
      if (historyRes.ok) {
        const data = await historyRes.json();
        const history: Message[] = (data.messages ?? []).map((m: Record<string, unknown>) => ({
          id: String(m.id ?? crypto.randomUUID()),
          role: m.role as Message["role"],
          content: m.content as string,
          timestamp: (m.timestamp as string) ?? new Date().toISOString(),
          approval_required: false,
        }));
        if (history.length > 0) {
          setMessages([
            {
              id: "welcome",
              role: "system",
              content: "SYUTAINβ に接続しました。ゴールを入力してください。",
              timestamp: new Date().toISOString(),
            },
            ...history,
          ]);
        }
      }
      if (budgetRes && budgetRes.ok) {
        const bj = await budgetRes.json();
        setChatBudget({
          spent: bj.chat_spent_jpy ?? 0,
          limit: bj.chat_budget_jpy ?? 30,
        });
      }
    } catch {
      // 履歴取得失敗は無視
    }
  }, []);

  const addTypingIndicator = useCallback(() => {
    setIsLoading(true);
    setMessages((prev) => [
      ...prev.filter((m) => m.id !== TYPING_INDICATOR_ID),
      {
        id: TYPING_INDICATOR_ID,
        role: "system",
        content: "考え中...",
        timestamp: new Date().toISOString(),
      },
    ]);
  }, []);

  const removeTypingIndicator = useCallback(() => {
    setIsLoading(false);
    setMessages((prev) => prev.filter((m) => m.id !== TYPING_INDICATOR_ID));
  }, []);

  const connect = useCallback(() => {
    try {
      const wsHost = typeof window !== "undefined" ? window.location.host : "localhost:8000";
      const protocol = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss" : "ws";
      const token = typeof window !== "undefined" ? localStorage.getItem("syutain_token") || "" : "";
      const ws = new WebSocket(`${protocol}://${wsHost}/api/chat/ws?token=${token}`);
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        setTimeout(connect, 3000);
      };
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          // 予算更新メッセージ
          if (data.type === "budget_update") {
            setChatBudget((prev) => ({
              ...prev,
              spent: data.daily_spent_jpy ?? data.chat_spent_jpy ?? prev.spent,
            }));
            return;
          }

          removeTypingIndicator();

          if (data.streaming && !data.done) {
            // ストリーミング中: 既存メッセージにトークン追加
            setMessages((prev) => {
              const existing = prev.find((m) => m.id === data.id);
              if (existing) {
                return prev.map((m) =>
                  m.id === data.id ? { ...m, content: m.content + data.content } : m
                );
              }
              // 新規ストリーミングメッセージ
              return [
                ...prev,
                {
                  id: data.id,
                  role: "assistant" as const,
                  content: data.content,
                  timestamp: new Date().toISOString(),
                },
              ];
            });
          } else if (data.done) {
            // ストリーミング完了: 最終メッセージで置換
            setMessages((prev) => {
              const existing = prev.find((m) => m.id === data.id);
              if (existing) {
                return prev.map((m) =>
                  m.id === data.id
                    ? { ...m, content: data.content, model_used: data.model_used, action: data.action, approval_required: data.approval_required, approval_id: data.approval_id }
                    : m
                );
              }
              return [...prev, data as Message];
            });
          } else {
            // 通常メッセージ（非ストリーミング）
            setMessages((prev) => [...prev, data as Message]);
          }
        } catch {
          // ignore malformed messages
        }
      };
      wsRef.current = ws;
    } catch {
      setConnected(false);
      setTimeout(connect, 3000);
    }
  }, [removeTypingIndicator]);

  useEffect(() => {
    loadHistory();
    connect();
    return () => wsRef.current?.close();
  }, [connect, loadHistory]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  // iOS Safari キーボード表示時のレイアウト調整
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;

    const handleResize = () => {
      const keyboardHeight = window.innerHeight - vv.height;
      document.documentElement.style.setProperty(
        "--keyboard-height",
        keyboardHeight > 100 ? `${keyboardHeight}px` : "0px"
      );
      // キーボード表示時にスクロール位置を調整
      if (keyboardHeight > 100) {
        setTimeout(() => {
          scrollRef.current?.scrollTo({ top: scrollRef.current!.scrollHeight, behavior: "smooth" });
        }, 100);
      }
    };

    vv.addEventListener("resize", handleResize);
    vv.addEventListener("scroll", handleResize);
    return () => {
      vv.removeEventListener("resize", handleResize);
      vv.removeEventListener("scroll", handleResize);
    };
  }, []);

  const sendViaHttp = async (text: string) => {
    try {
      const res = await apiFetch("/api/chat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: "default" }),
      });
      removeTypingIndicator();
      if (res.ok) {
        const data = await res.json();
        const reply: Message = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: data.reply ?? data.content ?? JSON.stringify(data),
          timestamp: new Date().toISOString(),
          approval_required: data.approval_required,
          approval_id: data.approval_id,
          model_used: data.metadata?.model_used,
          action: data.action,
        };
        setMessages((prev) => [...prev, reply]);

        // ゴール判定された場合にシステムメッセージを追加
        if (data.action === "goal_packet_draft" || data.action === "goal_created") {
          setMessages((prev) => [
            ...prev,
            {
              id: crypto.randomUUID(),
              role: "system",
              content: "🎯 ゴールとして受け付けました",
              timestamp: new Date().toISOString(),
            },
          ]);
        }
      } else {
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: "system",
            content: "応答の取得に失敗しました。再送信してください。",
            timestamp: new Date().toISOString(),
          },
        ]);
      }
    } catch {
      removeTypingIndicator();
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "system",
          content: "サーバーに接続できません。",
          timestamp: new Date().toISOString(),
        },
      ]);
    }
  };

  const sendMessage = () => {
    const text = input.trim();
    if (!text || isLoading) return;

    const msg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, msg]);
    setInput("");

    addTypingIndicator();

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "message", content: text }));
    } else {
      sendViaHttp(text);
    }
  };

  const retryLastMessage = () => {
    const lastUserMsg = [...messages].reverse().find((m) => m.role === "user");
    if (lastUserMsg) {
      addTypingIndicator();
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "message", content: lastUserMsg.content }));
      } else {
        sendViaHttp(lastUserMsg.content);
      }
    }
  };

  const handleApproval = (approvalId: string, approved: boolean) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "approval", approval_id: approvalId, approved }));
    }
    setMessages((prev) =>
      prev.map((m) =>
        m.approval_id === approvalId ? { ...m, approval_required: false, content: m.content + (approved ? "\n[承認済]" : "\n[却下]") } : m
      )
    );
  };

  const lastSystemError = messages.length > 0 && messages[messages.length - 1].role === "system" &&
    messages[messages.length - 1].content.includes("失敗");

  return (
    <div className="flex flex-col rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)]" style={{ height: "calc(100dvh - 8rem - var(--keyboard-height, 0px))" }}>
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--border-color)] px-4 py-3">
        <h2 className="font-semibold">SYUTAINβ チャット</h2>
        <div className="flex items-center gap-3">
          <span className="text-xs text-[var(--text-secondary)]">
            💬 ¥{chatBudget.spent.toFixed(0)}/¥{chatBudget.limit}
          </span>
          <span className={`flex items-center gap-1.5 text-xs ${connected ? "text-[var(--accent-green)]" : "text-[var(--accent-amber)]"}`}>
            <span className={`h-2 w-2 rounded-full ${connected ? "bg-[var(--accent-green)]" : "bg-[var(--accent-amber)]"}`} />
            {connected ? "接続中" : "HTTP"}
          </span>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] sm:max-w-[80%] rounded-lg px-4 py-2.5 ${
                msg.role === "user"
                  ? "bg-[var(--accent-purple)] text-white"
                  : msg.role === "system"
                  ? "bg-[var(--bg-primary)] text-[var(--text-secondary)] text-sm"
                  : "bg-[var(--bg-secondary)] border border-[var(--border-color)]"
              } ${msg.id === TYPING_INDICATOR_ID ? "animate-pulse" : ""}`}
            >
              {/* ゴール判定バッジ */}
              {msg.action && (msg.action === "goal_packet_draft" || msg.action === "goal_created") && (
                <div className="flex items-center gap-1 mb-1.5 text-xs text-[var(--accent-purple)]">
                  <Target className="h-3 w-3" />
                  ゴール受付
                </div>
              )}
              <p className="whitespace-pre-wrap text-sm">{msg.content}</p>
              {msg.approval_required && msg.approval_id && (
                <div className="mt-2 flex gap-2">
                  <button
                    onClick={() => handleApproval(msg.approval_id!, true)}
                    className="flex items-center gap-1 rounded-md bg-[var(--accent-green)]/20 px-3 py-1 text-xs text-[var(--accent-green)] hover:bg-[var(--accent-green)]/30 transition-colors"
                  >
                    <CheckCircle className="h-3 w-3" /> 承認
                  </button>
                  <button
                    onClick={() => handleApproval(msg.approval_id!, false)}
                    className="flex items-center gap-1 rounded-md bg-[var(--accent-red)]/20 px-3 py-1 text-xs text-[var(--accent-red)] hover:bg-[var(--accent-red)]/30 transition-colors"
                  >
                    <XCircle className="h-3 w-3" /> 却下
                  </button>
                </div>
              )}
              {msg.id !== TYPING_INDICATOR_ID && (
                <div className="mt-1 flex items-center justify-end gap-2">
                  {msg.model_used && msg.role === "assistant" && (
                    <span className="text-[10px] text-[var(--text-secondary)]">
                      via {msg.model_used}
                    </span>
                  )}
                  <span className="text-[10px] text-[var(--text-secondary)]">
                    {new Date(msg.timestamp).toLocaleTimeString("ja-JP")}
                  </span>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Input */}
      <div className="border-t border-[var(--border-color)] p-3">
        {lastSystemError && (
          <button
            onClick={retryLastMessage}
            className="mb-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-[var(--border-color)] bg-[var(--bg-primary)] py-2 text-xs text-[var(--text-secondary)] hover:text-white transition-colors"
          >
            <RefreshCw className="h-3 w-3" /> 再送信
          </button>
        )}
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage()}
            placeholder="ゴールやメッセージを入力..."
            className="flex-1 rounded-lg border border-[var(--border-color)] bg-[var(--bg-primary)] px-4 py-2.5 text-sm text-white placeholder-[var(--text-secondary)] outline-none focus:border-[var(--accent-purple)] transition-colors"
            disabled={isLoading}
          />
          <button
            onClick={sendMessage}
            disabled={isLoading}
            className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--accent-purple)] text-white hover:bg-[var(--accent-purple)]/80 transition-colors disabled:opacity-50"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
