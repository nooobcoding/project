// backend/app/schemas/auth.py 1:1 대응 (docs/02-coding-conventions.md 9장)

export interface RegisterRequest {
  email: string;
  password: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface EmailAvailabilityResponse {
  available: boolean;
}
