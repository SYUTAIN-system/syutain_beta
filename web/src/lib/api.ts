/**
 * SYUTAINβ API クライアント
 * JWT認証を自動管理し、全fetch呼び出しにAuthorizationヘッダーを付与する。
 * トークンはlocalStorageに保存し、期限切れ時は再ログインを要求する。
 * セキュリティ: パスワードはlocalStorageに保存しない。
 */

let _token: string | null = null;
let _tokenExpiry: number = 0;

function loadTokenFromStorage(): boolean {
  if (typeof window === "undefined") return false;
  const stored = localStorage.getItem("syutain_token");
  const storedExpiry = Number(localStorage.getItem("syutain_token_expiry") || "0");
  if (stored && Date.now() < storedExpiry) {
    _token = stored;
    _tokenExpiry = storedExpiry;
    return true;
  }
  return false;
}

async function getToken(): Promise<string> {
  // メモリキャッシュ確認
  if (_token && Date.now() < _tokenExpiry) {
    return _token;
  }

  // localStorage確認
  if (loadTokenFromStorage()) {
    return _token || "";
  }

  // トークンなし or 期限切れ — 再ログインが必要
  return _token || "";
}

/**
 * 認証付きfetch。JWTトークンを自動付与する。
 * 401が返った場合、トークンをクリアする（再ログインが必要）。
 */
export async function apiFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const token = await getToken();
  const headers = new Headers(init?.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetch(input, { ...init, headers });

  // 401の場合、トークンをクリア
  if (res.status === 401 && token) {
    _token = null;
    _tokenExpiry = 0;
    if (typeof window !== "undefined") {
      localStorage.removeItem("syutain_token");
      localStorage.removeItem("syutain_token_expiry");
    }
  }

  return res;
}

/**
 * WebSocket接続用のトークン取得
 */
export async function getWsToken(): Promise<string> {
  return getToken();
}

/**
 * ログイン（パスワードでトークンを取得し、トークンのみ保存）
 */
export async function login(password: string): Promise<boolean> {
  _token = null;
  _tokenExpiry = 0;

  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });

    if (res.ok) {
      const data = await res.json();
      const token = data.token || data.access_token || "";
      const expiresInHours = data.expires_in_hours || 24;
      const expiry = Date.now() + expiresInHours * 3600 * 1000 - 60000;

      _token = token;
      _tokenExpiry = expiry;

      if (typeof window !== "undefined") {
        localStorage.setItem("syutain_token", token);
        localStorage.setItem("syutain_token_expiry", String(expiry));
        // セキュリティ: 旧バージョンで保存されたパスワードを削除
        localStorage.removeItem("syutain_password");
      }

      return !!token;
    }
  } catch {
    // ログイン失敗
  }

  return false;
}

/**
 * ログイン済みか確認（トークンの存在と有効期限で判定）
 */
export function isLoggedIn(): boolean {
  if (typeof window === "undefined") return false;
  const stored = localStorage.getItem("syutain_token");
  const storedExpiry = Number(localStorage.getItem("syutain_token_expiry") || "0");
  return !!stored && Date.now() < storedExpiry;
}

/**
 * ログアウト
 */
export function logout(): void {
  _token = null;
  _tokenExpiry = 0;
  if (typeof window !== "undefined") {
    localStorage.removeItem("syutain_token");
    localStorage.removeItem("syutain_token_expiry");
    localStorage.removeItem("syutain_password");
  }
}
