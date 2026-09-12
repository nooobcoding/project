import { apiFetch } from "./client";
import type { Account, PasswordChangeInput } from "../types/account";

export function getAccount(token: string): Promise<Account> {
  return apiFetch<Account>("/api/account", { token });
}

export function changePassword(token: string, input: PasswordChangeInput): Promise<void> {
  return apiFetch<void>("/api/account/password", {
    method: "PATCH",
    token,
    body: JSON.stringify(input),
  });
}

export function deleteAccount(token: string): Promise<void> {
  return apiFetch<void>("/api/account", { method: "DELETE", token });
}
