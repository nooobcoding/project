"""첫 관리자 지정·권한 회수 CLI (확장판 05-admin.md 2.1절).

화면에서 스스로 관리자로 승격하는 경로는 두지 않는다. 권한은 이 스크립트로만 바꾼다.

사용법 (컨테이너 안에서):
    docker compose exec backend python scripts/set_admin.py user@example.com
    docker compose exec backend python scripts/set_admin.py user@example.com --revoke
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import session_scope  # noqa: E402
from app.models.user import ROLE_ADMIN, ROLE_USER  # noqa: E402
from app.services.admin import LastAdminError, UserNotFoundError, set_role  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="관리자 권한 부여·회수")
    parser.add_argument("email")
    parser.add_argument("--revoke", action="store_true", help="관리자 권한을 회수한다")
    args = parser.parse_args()

    role = ROLE_USER if args.revoke else ROLE_ADMIN
    try:
        with session_scope() as db:
            user = set_role(db, args.email, role)
            print(f"{user.email}: role={user.role}")
    except UserNotFoundError:
        print(f"해당 이메일의 유저가 없습니다: {args.email}", file=sys.stderr)
        return 1
    except LastAdminError:
        print("관리자가 최소 1명은 있어야 합니다.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
