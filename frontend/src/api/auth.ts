import { apiFetch } from "./client";
import type {
  EmailAvailabilityResponse,
  LoginRequest,
  RegisterRequest,
  TokenResponse,
} from "../types/auth";

export function register(payload: RegisterRequest): Promise<TokenResponse> {
  return apiFetch<TokenResponse>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function login(payload: LoginRequest): Promise<TokenResponse> {
  return apiFetch<TokenResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function logout(token: string): Promise<void> {
  return apiFetch<void>("/api/auth/logout", { method: "POST", token });
}

export function checkEmailAvailable(email: string): Promise<EmailAvailabilityResponse> {
  return apiFetch<EmailAvailabilityResponse>(
    `/api/auth/check-email?email=${encodeURIComponent(email)}`,
  );
}
