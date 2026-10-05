// 공용 fetch 래퍼. 서버 통신 실패와 서버가 반환한 오류를 구분해 각기 다른 메시지를 던진다
// (docs/features/01-auth.md 4장 오류 처리 표 참고).

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const NETWORK_ERROR_MESSAGE = "서버와 연결할 수 없습니다. 잠시 후 다시 시도해주세요.";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

// 서버(services/auth.py SUSPENDED_MESSAGE)와 같은 문구. 정지는 기존 토큰에도 즉시 적용되므로
// (확장판 05-admin.md 2.2절), 로그인한 채로 쓰던 화면의 아무 요청에서나 이 응답이 올 수 있다.
export const SUSPENDED_MESSAGE = "정지된 계정입니다. 관리자에게 문의해주세요.";

// apiFetch는 React 밖이라 로그아웃을 직접 못 한다 — AuthProvider가 처리기를 등록해 둔다.
let suspendedHandler: (() => void) | null = null;

export function setSuspendedHandler(handler: (() => void) | null): void {
  suspendedHandler = handler;
}

interface ApiFetchOptions extends RequestInit {
  token?: string;
}

export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { token, headers, ...rest } = options;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...rest,
      headers: {
        ...(rest.body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
    });
  } catch {
    throw new ApiError(NETWORK_ERROR_MESSAGE, 0);
  }

  if (!response.ok) {
    const detail = await extractErrorDetail(response);
    // 토큰을 실어 보낸 요청만 — 로그인 시도의 403은 폼이 메시지로 보여주면 된다.
    if (response.status === 403 && detail === SUSPENDED_MESSAGE && token) {
      suspendedHandler?.();
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

// CSV 내보내기(api/portfolio.ts)처럼 apiFetch를 쓸 수 없는 raw fetch 응답에도 같은 오류
// 추출 로직을 재사용한다 — 서버가 JSON 오류를 던지는 방식은 응답 Content-Type과 무관하다.
export async function extractErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") {
      return body.detail;
    }
    // Pydantic 검증 오류 형태: "Value error, <메시지>"에서 메시지만 추출
    if (Array.isArray(body.detail) && typeof body.detail[0]?.msg === "string") {
      return String(body.detail[0].msg).replace(/^Value error,\s*/, "");
    }
  } catch {
    // 응답 본문이 JSON이 아닌 경우 아래 기본 메시지로 대체
  }
  return NETWORK_ERROR_MESSAGE;
}
