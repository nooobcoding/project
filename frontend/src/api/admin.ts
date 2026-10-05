import { apiFetch } from "./client";
import type { StrategySlot } from "../types/strategySlots";
import type {
  AdminUserDetail,
  AdminUserListParams,
  AdminUserListResponse,
  AdminUserStatusResult,
  AuditLogListResponse,
  SystemOverview,
  UserStatus,
} from "../types/admin";

// 확장판 05-admin.md — /api/admin/*. 권한 검사는 서버가 한다(프론트 가드는 편의일 뿐).

export function listUsers(token: string, params: AdminUserListParams): Promise<AdminUserListResponse> {
  const query = new URLSearchParams({
    sort: params.sort,
    page: String(params.page),
    page_size: String(params.pageSize),
  });
  if (params.status) query.set("status", params.status);
  if (params.hasActiveSlots !== null) query.set("has_active_slots", String(params.hasActiveSlots));
  if (params.q.trim()) query.set("q", params.q.trim());
  return apiFetch<AdminUserListResponse>(`/api/admin/users?${query}`, { token });
}

export function getUser(token: string, userId: number): Promise<AdminUserDetail> {
  return apiFetch<AdminUserDetail>(`/api/admin/users/${userId}`, { token });
}

export function setUserStatus(token: string, userId: number, status: UserStatus): Promise<AdminUserStatusResult> {
  return apiFetch<AdminUserStatusResult>(`/api/admin/users/${userId}/status`, {
    method: "PATCH",
    token,
    body: JSON.stringify({ status }),
  });
}

export function deactivateSlot(token: string, slotId: number): Promise<StrategySlot> {
  return apiFetch<StrategySlot>(`/api/admin/strategy-slots/${slotId}/deactivate`, {
    method: "POST",
    token,
  });
}

export function getSystemOverview(token: string): Promise<SystemOverview> {
  return apiFetch<SystemOverview>("/api/admin/system", { token });
}

export function listAuditLogs(
  token: string,
  params: { action: string | null; targetId: number | null; page: number; pageSize: number },
): Promise<AuditLogListResponse> {
  const query = new URLSearchParams({ page: String(params.page), page_size: String(params.pageSize) });
  if (params.action) query.set("action", params.action);
  if (params.targetId !== null) query.set("target_id", String(params.targetId));
  return apiFetch<AuditLogListResponse>(`/api/admin/audit-logs?${query}`, { token });
}
