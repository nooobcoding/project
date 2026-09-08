// 공용 fetch 래퍼. 서버 통신 실패와 서버가 반환한 오류를 구분해 각기 다른 메시지를 던진다
// (docs/features/01-auth.md 4장 오류 처리 표 참고).

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const NETWORK_ERROR_MESSAGE = "서버와 연결할 수 없습니다. 잠시 후 다시 시도해주세요.";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
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
    throw new ApiError(await extractErrorDetail(response), response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

async function extractErrorDetail(response: Response): Promise<string> {
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
