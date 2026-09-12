import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { changePassword, deleteAccount, getAccount } from "../../api/account";
import { ApiError } from "../../api/client";
import { useAuth } from "../../hooks/useAuth";
import { PasswordInput } from "../PasswordInput";
import { DeleteAccountModal } from "./DeleteAccountModal";

// 01-auth.md 2-B와 동일 규칙 — backend/app/schemas/account.py의 검증과 동기화되어야 한다
const PASSWORD_PATTERN = /^(?=.*[A-Za-z])(?=.*\d).{8,}$/;

interface AccountSettingsPanelProps {
  onToast: (message: string) => void;
}

export function AccountSettingsPanel({ onToast }: AccountSettingsPanelProps) {
  const { token, logout } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState<string | null>(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newPasswordConfirm, setNewPasswordConfirm] = useState("");
  const [currentPasswordError, setCurrentPasswordError] = useState<string | undefined>();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);

  useEffect(() => {
    if (!token) return;
    getAccount(token)
      .then((account) => setEmail(account.email))
      .catch(() => undefined);
  }, [token]);

  const newPasswordError =
    newPassword.length === 0
      ? undefined
      : !PASSWORD_PATTERN.test(newPassword)
        ? "비밀번호는 8자 이상, 영문과 숫자를 포함해야 합니다."
        // 패턴 오류를 먼저 보여준다 — 둘 다 해당하면 "너무 짧다"보다 이쪽이 덜 급하다.
        : newPassword === currentPassword
          ? "새 비밀번호는 현재 비밀번호와 달라야 합니다."
          : undefined;
  const newPasswordConfirmError =
    newPasswordConfirm.length > 0 && newPasswordConfirm !== newPassword
      ? "비밀번호가 일치하지 않습니다."
      : undefined;

  const isValid =
    currentPassword.length > 0 &&
    PASSWORD_PATTERN.test(newPassword) &&
    newPassword !== currentPassword &&
    newPasswordConfirm === newPassword;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isValid || !token) return;

    setIsSubmitting(true);
    setCurrentPasswordError(undefined);
    try {
      await changePassword(token, {
        current_password: currentPassword,
        new_password: newPassword,
      });
      setCurrentPassword("");
      setNewPassword("");
      setNewPasswordConfirm("");
      onToast("비밀번호가 변경되었습니다.");
    } catch (err) {
      // 새 비밀번호가 현재 비밀번호와 같다는 오류(위에서 이미 막아 보통 도달하지 않음 —
      // 제출 직전 다른 곳에서 비밀번호가 바뀐 경우 등의 안전망)는 "현재 비밀번호" 필드
      // 오류가 아니므로 토스트로만 보여준다.
      if (err instanceof ApiError && err.status === 400 && err.message.includes("현재 비밀번호가 올바르지")) {
        setCurrentPasswordError(err.message);
      } else {
        onToast(err instanceof ApiError ? err.message : "비밀번호 변경에 실패했습니다.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteConfirm = async () => {
    if (!token) return;
    await deleteAccount(token);
    logout();
    navigate("/login");
  };

  return (
    <section className="settings-panel">
      <h2>계정 설정</h2>
      <div className="settings-field">
        <span className="settings-field-label">가입 이메일</span>
        <span className="settings-field-value">{email ?? "불러오는 중..."}</span>
      </div>
      <hr className="settings-divider" />
      <form className="auth-form" onSubmit={handleSubmit}>
        <PasswordInput
          label="현재 비밀번호"
          value={currentPassword}
          onChange={(value) => {
            setCurrentPassword(value);
            setCurrentPasswordError(undefined);
          }}
          error={currentPasswordError}
          autoComplete="current-password"
        />
        <PasswordInput
          label="새 비밀번호"
          value={newPassword}
          onChange={setNewPassword}
          error={newPasswordError}
          // "new-password"를 주면 크롬이 이 필드를 새 비밀번호 입력으로 인식해 자체 생성
          // 비밀번호를 제안하는 팝업을 띄운다. 이 화면은 사용자가 직접 정한 비밀번호를
          // 입력받는 게 목적이라 "off"로 그 제안을 끈다.
          autoComplete="off"
        />
        <PasswordInput
          label="새 비밀번호 확인"
          value={newPasswordConfirm}
          onChange={setNewPasswordConfirm}
          error={newPasswordConfirmError}
          autoComplete="off"
        />
        <button type="submit" className="auth-button" disabled={!isValid || isSubmitting}>
          {isSubmitting ? "변경 중..." : "비밀번호 변경"}
        </button>
      </form>
      <hr className="settings-divider" />
      <button
        type="button"
        className="settings-danger-button"
        onClick={() => setShowDeleteModal(true)}
      >
        회원 탈퇴
      </button>
      {showDeleteModal && (
        <DeleteAccountModal
          onClose={() => setShowDeleteModal(false)}
          onConfirm={handleDeleteConfirm}
        />
      )}
    </section>
  );
}
