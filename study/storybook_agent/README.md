# Storybook Agent

Google ADK 기반 어린이 동화책 자동 생성 에이전트.
두 에이전트가 ADK Session State를 공유하며 순차적으로 동작합니다.

## 에이전트 구조

```
사용자 입력 ("테마: ...")
        ↓
[StorybookAgent - SequentialAgent]
        ├── [StoryWriterAgent]
        │     - 도구: save_story(pages, characters)
        │     - gpt-4.1로 5페이지 한국어 동화 생성
        │     - State["story_pages"], State["story_characters"] 저장
        │
        └── [IllustratorAgent]
              - 도구: generate_illustrations()
              - State에서 페이지 + 캐릭터 정보 읽기
              - gpt-image-1로 이미지 생성 (페이지당 1장)
              - Artifact로 저장: page_1.png ~ page_5.png
```

## 파일 구성

| 파일 | 설명 |
|------|------|
| `agent.py` | 프롬프트 + 도구 + 에이전트 통합 (핵심 파일) |
| `__init__.py` | 패키지 초기화 |
| `code_mode.ipynb` | ADK Runner 직접 실행 방식 |
| `api_mode.ipynb` | ADK API 서버 방식 |
| `deploy.py` | Vertex AI 배포 스크립트 |
| `remote.py` | 배포된 앱 연결/삭제 스크립트 |

## 실행 방법

### 사전 준비

`.env` 파일에 OpenAI API 키 설정 (email-refiner-agent/ 루트):
```
OPENAI_API_KEY="sk-proj-..."
```

### adk web (로컬 테스트)

```powershell
cd email-refiner-agent
uv run adk web
```

브라우저에서 `http://localhost:8080` 접속 → `storybook_agent` 선택 → 테마 입력

```
테마: 용감한 토끼의 모험
```

- 텍스트 생성: 약 10~15초
- 이미지 5장 생성: 약 3~5분 (gpt-image-1 순차 생성)

---

## 개발 과정에서 발생한 에러 및 해결

### 1. `AsyncOpenAI` (httpx) hang 문제

**증상:** `generate_illustrations` 단계에서 에이전트가 무한 대기 상태로 멈춤. 터미널 로그에 아무 출력 없음.

**원인:** ADK는 자체 async 이벤트 루프를 사용하는데, `AsyncOpenAI` 클라이언트는 내부적으로 `httpx.AsyncClient`를 사용한다. 두 async 루프가 충돌하여 deadlock 발생.

**해결:** `AsyncOpenAI` → 동기 `OpenAI()` 클라이언트로 교체.

```python
# 변경 전 (hang 발생)
client = AsyncOpenAI()
response = await client.images.generate(...)

# 변경 후
client = OpenAI()
response = client.images.generate(...)
```

---

### 2. 동기 OpenAI 클라이언트가 이벤트 루프를 블로킹

**증상:** 동기 클라이언트로 교체 후에도 이미지 생성 중 adk web 서버 전체가 응답 없음 (다른 요청도 처리 불가).

**원인:** 동기 HTTP 호출이 ADK의 async 이벤트 루프 스레드를 점유하여 서버가 다른 작업을 처리 못함.

**해결:** `loop.run_in_executor(None, functools.partial(...))` 패턴으로 동기 호출을 별도 스레드 풀에서 실행.

```python
loop = asyncio.get_event_loop()
generate_fn = functools.partial(client.images.generate, model="gpt-image-1", ...)
response = await loop.run_in_executor(None, generate_fn)
```

---

### 3. `save_artifact` never awaited (RuntimeWarning)

**증상:** 터미널에 `RuntimeWarning: coroutine 'save_artifact' was never awaited` 출력. 이미지가 Artifact로 저장되지 않음.

**원인:** `generate_illustrations` 함수를 `def`로 선언했기 때문에 함수 내부에서 `await`를 사용할 수 없었고, `save_artifact()`의 coroutine이 실행되지 않고 버려짐.

**해결:** `def` → `async def`로 변경하고 `await` 추가.

```python
# 변경 전
def generate_illustrations(tool_context: ToolContext):
    tool_context.save_artifact(...)  # coroutine 버려짐

# 변경 후
async def generate_illustrations(tool_context: ToolContext):
    await tool_context.save_artifact(...)
```

---

### 4. `dall-e-2 does not exist` 에러

**증상:** `openai.NotFoundError: dall-e-2 does not exist` 발생.

**원인:** 최신 openai 라이브러리(1.x 이상)에서 `dall-e-2` 모델명이 deprecated되어 제거됨.

**해결:** `dall-e-2` → `gpt-image-1` 으로 교체.

```python
model="gpt-image-1"
```

---

### 5. `response_format` 파라미터 에러

**증상:** `openai.BadRequestError: Unknown parameter: 'response_format'` 발생.

**원인:** 최신 openai 라이브러리의 이미지 생성 API에서 `response_format` 파라미터가 제거됨. `gpt-image-1`은 기본적으로 `b64_json`을 반환.

**해결:** `response_format` 파라미터 제거. 응답 처리 방식은 `response.data[0].b64_json`으로 유지.

```python
# 제거
response_format="b64_json"

# b64_json은 기본값이므로 그대로 사용 가능
image_bytes = base64.b64decode(response.data[0].b64_json)
```

---

### 6. 이미지 캐릭터 불일치 (페이지마다 다른 캐릭터 등장)

**증상:** 1페이지는 흰 토끼가 나오지만 2페이지부터 거북이 등 전혀 다른 동물이 등장.

**원인:** 각 페이지 이미지를 독립적으로 생성할 때, 이미지 프롬프트에 캐릭터 외형 정보가 없으면 모델이 페이지마다 캐릭터를 새롭게 해석함.

**해결:** StoryWriterAgent가 스토리 저장 시 `characters` 인자(캐릭터 외형 묘사)도 함께 저장하도록 수정. IllustratorAgent는 모든 페이지 이미지 프롬프트 앞에 캐릭터 설명을 추가.

```python
# save_story에 characters 파라미터 추가
def save_story(tool_context, pages, characters=""):
    tool_context.state["story_pages"] = pages
    tool_context.state["story_characters"] = characters

# generate_illustrations에서 캐릭터 설명을 프롬프트에 주입
characters = tool_context.state.get("story_characters", "")
character_prefix = f"캐릭터 설정 (반드시 유지): {characters}. " if characters else ""

prompt = (
    f"어린이 동화책 삽화, 부드러운 수채화 스타일, 귀엽고 친근한 캐릭터. "
    f"{character_prefix}"
    f"이번 장면: {page['visual']}"
)
```

---

## 핵심 기술

| 기술 | 용도 |
|------|------|
| `SequentialAgent` | StoryWriter → Illustrator 순차 실행 |
| `tool_context.state` | 에이전트 간 데이터 공유 (story_pages, story_characters) |
| `tool_context.save_artifact` | 생성된 이미지를 ADK Artifact로 저장 |
| `LiteLlm` | ADK에서 OpenAI 모델 사용을 위한 브릿지 |
| `run_in_executor` | 동기 OpenAI 클라이언트를 async 환경에서 블로킹 없이 실행 |
| `base64.b64decode` | gpt-image-1 응답(b64_json)을 바이트로 변환 |
