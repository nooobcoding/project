// backend/app/schemas/account.py 1:1 대응 (docs/02-coding-conventions.md 9장)

export interface Account {
  email: string;
}

export interface PasswordChangeInput {
  current_password: string;
  new_password: string;
}
