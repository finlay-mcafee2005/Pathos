// Login session: the user's id plus the signed token the backend gave us.
// Every request to the backend carries the token, and the backend only
// returns data for the user it belongs to.
import { API_URL } from "./format";

const USER_KEY = "user_id";
const TOKEN_KEY = "auth_token";

export function saveSession(userId: string, token: string) {
  localStorage.setItem(USER_KEY, userId);
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearSession() {
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(TOKEN_KEY);
  try { sessionStorage.removeItem("pathos_me"); sessionStorage.removeItem("pathos_verify_hidden"); } catch { /* ignore */ }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

// Logged in = we have both an id and a token. Accounts from before tokens
// existed have only an id, so they're sent to log in once more.
export function isLoggedIn(): boolean {
  return !!localStorage.getItem(USER_KEY) && !!getToken();
}

// Wraps window.fetch so every backend call sends the token, and an expired
// or missing session sends the user back to the login page.
export function installAuthFetch() {
  const original = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const isApi = url.startsWith(API_URL);
    const token = getToken();
    if (isApi && token) {
      const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
      if (!headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
      init = { ...init, headers };
    }
    const response = await original(input, init);
    const isAuthCall = /\/(login|signup)$/.test(url);
    if (isApi && response.status === 401 && !isAuthCall) {
      clearSession();
      if (!window.location.pathname.startsWith("/login")) {
        window.location.assign("/login?expired=1");
      }
    }
    return response;
  };
}
