"""FastAPI 앱 진입점.

지금은 헬스체크 라우터만 등록한 스캐폴딩 상태다. 기능별 라우터는
routers/ 아래에 추가되는 대로 여기서 include_router로 연결한다
(docs/02-coding-conventions.md 6장 프로젝트 구조 참고).
"""

from fastapi import FastAPI

app = FastAPI(title="코인 자동매매 프로그램 API")


@app.get("/health")
def health_check() -> dict[str, str]:
    """서버 생존 확인용 헬스체크 엔드포인트."""
    return {"status": "ok"}
