import { createContext, useMemo, useState, type ReactNode } from "react";
import * as authApi from "../api/auth";

const TOKEN_STORAGE_KEY = "coin_autotrading_token";

export interface AuthContextValue {
  token: string | null;
  isAuthenticated: boolean;
  login: (email: string, password: string, remember: boolean) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function readStoredToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY) ?? sessionStorage.getItem(TOKEN_STORAGE_KEY);
}

function storeToken(token: string, remember: boolean): void {
  const storage = remember ? localStorage : sessionStorage;
  storage.setItem(TOKEN_STORAGE_KEY, token);
}

function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
  sessionStorage.removeItem(TOKEN_STORAGE_KEY);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => readStoredToken());

  const value = useMemo<AuthContextValue>(
    () => ({
      token,
      isAuthenticated: token !== null,
      login: async (email, password, remember) => {
        const response = await authApi.login({ email, password });
        storeToken(response.access_token, remember);
        setToken(response.access_token);
      },
      register: async (email, password) => {
        const response = await authApi.register({ email, password });
        // 회원가입 폼엔 "로그인 유지" 체크박스가 없다 — 가입 직후 자동 로그인은
        // 로그인 유지를 선택한 것과 동일하게 취급한다 (01-auth.md 2-B).
        storeToken(response.access_token, true);
        setToken(response.access_token);
      },
      logout: () => {
        const currentToken = token;
        clearStoredToken();
        setToken(null);
        if (currentToken) {
          // 01-auth.md 7장 — 감사 로그용 엔드포인트라 실패해도 클라이언트 로그아웃은 이미 끝난 상태
          authApi.logout(currentToken).catch(() => undefined);
        }
      },
    }),
    [token],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
