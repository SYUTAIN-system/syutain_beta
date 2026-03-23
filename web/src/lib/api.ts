/**
 * SYUTAINβ API クライアント
 * JWT認証を自動管理し、全fetch呼び出しにAuthorizationヘッダーを付与する。
 * トークンはlocalStorageに保存し、期限切れ時に自動再取得する。
 */

let _token: string | null = null;
let _tokenExpiry: number = 0;

async function getToken(): Promise<string> {
  // メモリキャッシュ確認
  if (_token && Date.now() < _tokenExpiry) {
    return _token;
  }

  // localStorage確認
  if (typeof window !== "undefined") {
    const stored = localStorage.getItem("syutain_token");
    const storedExpiry = Number(localStorage.getItem("syutain_token_expiry") || "0");
    if (stored && Date.now() < storedExpiry) {
      _token = stored;
      _tokenExpiry = storedExpiry;
      return stored;
    }
  }

  // 新規トークン取得
  const password = typeof window !== "undefined"
    ? localStorage.getItem("syutain_password") || ""
    : "";

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
      const expiry = Date.now() + expiresInHours * 3600 * 1000 - 60000; // 1分前にexpire

      _token = token;
      _tokenExpiry = expiry;

      if (typeof window !== "undefined") {
        localStorage.setItem("syutain_token", token);
        localStorage.setItem("syutain_token_expiry", String(expiry));
      }

      return token;
    }
  } catch {
    // ログインに失敗した場合は空トークンで続行（401が返る）
  }

  return _token || "";
}

/**
 * 認証付きfetch。JWTトークンを自動付与する。
 * 401が返った場合、トークンをクリアして1回だけ再試行する。
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

  // 401の場合、トークンをクリアして再取得を試みる
  if (res.status === 401 && token) {
    _token = null;
    _tokenExpiry = 0;
    if (typeof window !== "undefined") {
      localStorage.removeItem("syutain_token");
      localStorage.removeItem("syutain_token_expiry");
    }

    const newToken = await getToken();
    if (newToken && newToken !== token) {
      const retryHeaders = new Headers(init?.headers);
      retryHeaders.set("Authorization", `Bearer ${newToken}`);
      return fetch(input, { ...init, headers: retryHeaders });
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
 * ログイン（パスワードをlocalStorageに保存し、トークンを取得）
 */
export async function login(password: string): Promise<boolean> {
  if (typeof window !== "undefined") {
    localStorage.setItem("syutain_password", password);
  }
  _token = null;
  _tokenExpiry = 0;

  const token = await getToken();
  return !!token;
}

/**
 * ログイン済みか確認
 */
export function isLoggedIn(): boolean {
  if (typeof window === "undefined") return false;
  return !!localStorage.getItem("syutain_password");
}
