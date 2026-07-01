import vertexai
from vertexai import agent_engines

PROJECT_ID = "gen-lang-client-0125196626"
LOCATION = "europe-southwest1"

vertexai.init(
    project=PROJECT_ID,
    location=LOCATION,
)

# deployments = agent_engines.list()
# for deployment in deployments:
#     print(deployment)

# deploy.py 실행 후 출력된 ID로 교체하세요
DEPLOYMENT_ID = "projects/23382131925/locations/europe-southwest1/reasoningEngines/REPLACE_AFTER_DEPLOY"

SESSION_ID = ""

remote_app = agent_engines.get(DEPLOYMENT_ID)

# ── 세션 생성 ─────────────────────────────────────────────
# remote_session = remote_app.create_session(user_id="u_123")
# SESSION_ID = remote_session["id"]
# print(SESSION_ID)

# ── 스토리 생성 요청 ──────────────────────────────────────
# for event in remote_app.stream_query(
#     user_id="u_123",
#     session_id=SESSION_ID,
#     message="테마: 용감한 토끼 베니의 모험",
# ):
#     print(event, "\n", "=" * 50)

# ── 배포 삭제 ─────────────────────────────────────────────
# remote_app.delete(force=True)
