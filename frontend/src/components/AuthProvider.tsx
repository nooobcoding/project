import { createContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { getAccount } from "../api/account";
import * as authApi from "../api/auth";
import { SUSPENDED_MESSAGE, setSuspendedHandler } from "../api/client";

const TOKEN_STORAGE_KEY = "coin_autotrading_token";

export type Role = "user" | "admin";

export interface AuthContextValue {
  token: string | null;
  isAuthenticated: boolean;
  // null = 아직 모름(계정 조회 중이거나 실패). 관리자 화면 가드는 이걸 "관리자 아님"으로 단정하지
  // 않고 기다린다 — 단정하면 새로고침할 때마다 관리자가 대시보드로 튕겨 나간다.
  role: Role | null;
  // 로그인 화면에 한 번 띄울 안내 (정지로 강제 로그아웃된 경우)
  notice: string | null;
  clearNotice: () => void;
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
  const [role, setRole] = useState<Role | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // 정지는 기존 토큰에도 즉시 적용된다(확장판 05-admin.md 2.2절). 어느 화면의 어느 요청이든
  // 정지 응답을 받으면 토큰을 버리고 로그인 화면으로 보낸다 — 안 그러면 화면은 로그인 상태인데
  // 모든 요청이 실패하는 채로 남는다.
  useEffect(() => {
    setSuspendedHandler(() => {
      clearStoredToken();
      setToken(null);
      setNotice(SUSPENDED_MESSAGE);
    });
    return () => setSuspendedHandler(null);
  }, []);

  useEffect(() => {
    setRole(null);
    if (!token) return;
    let canceled = false;
    getAccount(token)
      .then((account) => {
        if (!canceled) setRole(account.role);
      })
      .catch(() => undefined);
    return () => {
      canceled = true;
    };
  }, [token]);

  const value = useMemo<AuthContextValue>(
    () => ({
      token,
      isAuthenticated: token !== null,
      role,
      notice,
      clearNotice: () => setNotice(null),
      login: async (email, password, remember) => {
        const response = await authApi.login({ email, password });
        storeToken(response.access_token, remember);
        setNotice(null);
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
    [token, role, notice],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
