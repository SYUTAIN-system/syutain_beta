"use client";

import { useState, useEffect } from "react";
import { login, isLoggedIn } from "@/lib/api";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [authed, setAuthed] = useState(false);
  const [checking, setChecking] = useState(true);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (isLoggedIn()) {
      setAuthed(true);
    }
    setChecking(false);

    // JWT期限切れ時のリアルタイム検出
    const handler = () => setAuthed(false);
    window.addEventListener("syutain:auth_expired", handler);
    return () => window.removeEventListener("syutain:auth_expired", handler);
  }, []);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    const ok = await login(password);
    if (ok) {
      setAuthed(true);
    } else {
      setError("パスワードが正しくありません");
    }
  };

  if (checking) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--accent-purple)] border-t-transparent" />
      </div>
    );
  }

  if (!authed) {
    return (
      <div className="flex h-screen items-center justify-center">
        <form onSubmit={handleLogin} className="w-80 space-y-4 rounded-xl border border-[var(--border-color)] bg-[var(--bg-card)] p-6">
          <h1 className="text-center text-xl font-bold">
            SYUTAIN<span className="text-[var(--accent-purple)]">β</span>
          </h1>
          <p className="text-center text-sm text-[var(--text-secondary)]">ログイン</p>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="パスワード"
            className="w-full rounded-lg border border-[var(--border-color)] bg-[var(--bg-primary)] px-4 py-2.5 text-sm focus:border-[var(--accent-purple)] focus:outline-none"
            autoFocus
          />
          {error && <p className="text-xs text-[var(--accent-red)]">{error}</p>}
          <button
            type="submit"
            className="w-full rounded-lg bg-[var(--accent-purple)] px-4 py-2.5 text-sm font-medium text-white hover:opacity-90"
          >
            ログイン
          </button>
        </form>
      </div>
    );
  }

  return <>{children}</>;
}
