# Storybook Agent

Google ADK의 **Workflow Agent**(SequentialAgent + ParallelAgent)를 활용한 어린이 동화책 자동 생성 파이프라인.
에이전트들이 ADK Session State를 공유하며, 스토리 작성 → 삽화 병렬 생성 순으로 동작합니다.

## 에이전트 구조

```
사용자 입력 ("테마: 용감한 아기 고양이 이야기")
        ↓
[StorybookAgent - SequentialAgent]        ← 전체 흐름 관리
        │  after_agent_callback: 완성된 동화책 최종 출력
        │
        ├── [StoryWriterAgent]
        │     - before_agent_callback: "📖 스토리 작성 중..."
        │     - 도구: save_story(title, pages, characters)
        │     - gpt-4.1로 5페이지 한국어 동화 + 제목 생성
        │     - State["story_title"/"story_pages"/"story_characters"] 저장
        │
        └── [ParallelIllustratorAgent - ParallelAgent]   ← 5장 동시 생성
              ├── [IllustratorAgent1]  before_cb: "🎨 이미지 1/5 생성 중..."
              ├── [IllustratorAgent2]  before_cb: "🎨 이미지 2/5 생성 중..."
              ├── [IllustratorAgent3]  before_cb: "🎨 이미지 3/5 생성 중..."
              ├── [IllustratorAgent4]  before_cb: "🎨 이미지 4/5 생성 중..."
              └── [IllustratorAgent5]  before_cb: "🎨 이미지 5/5 생성 중..."
                    - 도구: generate_illustration()  (담당 페이지 1장)
                    - State에서 페이지 + 캐릭터 정보 읽기
                    - gpt-image-1로 이미지 생성
                    - 삽화 하단에 동화 텍스트를 합성 (Pillow)
                    - Artifact 저장(page_N.png) + State에 이미지 보관
        ↓
[after_agent_callback] 1~5페이지 삽화를 순서대로 묶어
                       동화책 PDF 한 파일로 저장 → output/storybook.pdf
        ↓
[최종 출력] 제목 + 5페이지 텍스트 + 5페이지짜리 동화책 PDF 경로
```

## Workflow Agent 구성 요소

| 요구사항 | 구현 |
|----------|------|
| **SequentialAgent** | `StorybookAgent` — Writer → Illustrator 흐름 관리 |
| **ParallelAgent** | `ParallelIllustratorAgent` — 삽화 5장을 5개 sub-agent로 동시 생성 |
| **Callbacks** | `before_agent_callback`으로 진행 상황("스토리 작성 중...", "이미지 N/5 생성 중...") 표시, `after_agent_callback`으로 5페이지를 순서대로 묶어 동화책 PDF 한 파일로 조립 후 최종 출력 |

## 최종 산출물

- **`output/storybook.pdf`** — 제목·텍스트·삽화가 포함된 **5페이지짜리 동화책 한 파일** (1~5페이지 순서대로)
- 각 페이지는 gpt-image-1 삽화 + 하단에 합성된 동화 텍스트로 구성

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
테마: 용감한 아기 고양이 이야기
```

- 텍스트 생성: 약 10~15초
- 이미지 5장 생성: ParallelAgent로 동시 생성 (순차 대비 대폭 단축)

### 데모용 테마 예시 (최소 2가지)

```
테마: 용감한 아기 고양이 이야기
테마: 별을 모으는 작은 우주 여우
```

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

### 7. 순차 삽화 생성 → ParallelAgent 병렬 생성으로 전환 (이번 주 과제)

**배경:** 기존에는 `IllustratorAgent` 1개가 tool 내부 for 루프로 5장을 순차 생성했다. 이미지 1장당 시간이 길어 5장 완료까지 오래 걸렸다.

**변경:** Workflow Agent 요구사항에 맞춰 페이지별 삽화 에이전트 5개를 만들고 `ParallelAgent`로 묶어 동시에 생성하도록 리팩터링.

**주의점:** 과거에 단일 tool 내부에서 `asyncio.gather()`로 병렬 처리를 시도했을 때 하나의 `tool_context`를 공유하며 ADK 이벤트 루프와 충돌해 hang이 발생했다. 이번에는 tool factory(`make_generate_illustration(page_index)`)로 페이지별 tool을 생성하고, 각 sub-agent가 **독립된 tool_context**를 갖도록 하여 ADK 표준 병렬 패턴(`ParallelAgent`)으로 안전하게 처리했다. 동기 OpenAI 호출은 `run_in_executor`로 스레드 풀에 위임해 5개 요청이 동시에 진행된다.

```python
# 페이지별 tool을 만드는 factory (클로저로 page_index 고정)
def make_generate_illustration(page_index: int):
    async def generate_illustration(tool_context: ToolContext):
        page = tool_context.state.get("story_pages", [])[page_index]
        ...  # run_in_executor로 이미지 생성 후 save_artifact
    return generate_illustration

# 5개 sub-agent를 ParallelAgent로 동시 실행
parallel_illustrator_agent = ParallelAgent(
    name="ParallelIllustratorAgent",
    sub_agents=illustrator_agents,  # IllustratorAgent1 ~ 5
)
```

**Callbacks 추가:** `before_agent_callback`으로 각 단계 진행 상황을 콘솔에 표시하고, root `SequentialAgent`의 `after_agent_callback`으로 State를 읽어 완성된 동화책(제목 + 5페이지 + 삽화 파일명)을 최종 출력하도록 구현.

---

### 8. 동화책 페이지에 텍스트 삽입 (그림책 형태 완성)

**배경:** 삽화 이미지에는 그림만 있고 동화 텍스트가 없어, 실제 그림책처럼 "텍스트가 포함된 페이지"가 되지 못했다.

**원인:** gpt-image-1 같은 이미지 생성 모델은 한글 텍스트를 이미지 안에 정확히 렌더링하지 못한다(글자가 깨지거나 뭉개짐).

**해결:** `Pillow(PIL)`로 생성된 삽화 하단에 반투명 흰색 밴드를 깔고 그 위에 페이지 텍스트를 한글 폰트(맑은 고딕, `malgun.ttf`)로 직접 그려 넣는 `overlay_text()` 함수를 추가. 이미지 폭에 맞춘 한글 줄바꿈(`_wrap_korean`)도 구현. 이렇게 만든 PNG 자체가 "그림 + 글" 완성 페이지가 된다.

```python
def overlay_text(image_bytes: bytes, text: str) -> bytes:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 40)
    # 하단에 반투명 밴드 + 줄바꿈한 텍스트를 그림
    ...
    return png_bytes
```

> 참고: `malgun.ttf`는 Windows 로컬 폰트 경로다. 다른 OS(예: Vertex AI 배포 환경)에서는 폰트 경로를 해당 OS의 한글 폰트로 바꿔야 한다. `deploy.py`의 requirements에는 `pillow`를 추가했다.

---

### 9. 5개 개별 파일 → 5페이지짜리 동화책 PDF 한 파일로 통합

**배경:** 삽화가 페이지별로 5개의 개별 이미지로만 나와, "동화책 한 권" 형태가 아니었다. 요구사항은 1~5페이지가 순서대로 담긴 **한 개의 5페이지짜리 파일**.

**해결:** 병렬로 생성된 각 삽화(그림+텍스트)를 페이지 고유 키로 State에 보관하고(`state["page_image_N"]`), 모든 삽화 생성이 끝난 뒤 root의 `after_agent_callback`에서 1~5페이지 순서대로 모아 `Pillow`로 **멀티페이지 PDF 한 파일**(`output/storybook.pdf`)로 합친다.

```python
# 각 IllustratorAgent: 완성된 삽화를 페이지별 고유 키로 State에 저장 (병렬 충돌 방지)
tool_context.state[f"page_image_{page['page']}"] = base64.b64encode(image_bytes).decode()

# after_agent_callback: 1~5페이지 순서대로 모아 PDF 한 파일로 합침
def build_storybook_pdf(page_images: list):
    images = [Image.open(io.BytesIO(b)).convert("RGB") for b in page_images]
    images[0].save("output/storybook.pdf", format="PDF",
                   save_all=True, append_images=images[1:])
```

**병렬 안전성:** 5개 삽화 에이전트가 각자 `page_image_1`~`page_image_5`라는 **서로 다른 State 키**에 기록하므로 병렬 실행 중 충돌이 없다. 합치는 작업은 모든 병렬 작업이 끝난 뒤 `after_agent_callback`에서 한 번만 수행된다.

---

## 핵심 기술

| 기술 | 용도 |
|------|------|
| `SequentialAgent` | StoryWriter → ParallelIllustrator 순차 흐름 관리 |
| `ParallelAgent` | 삽화 5장을 5개 sub-agent로 동시 생성 |
| `before/after_agent_callback` | 진행 상황 표시 + 완성된 동화책 최종 조립 출력 |
| tool factory (클로저) | 페이지별 삽화 tool 생성 (각자 독립 tool_context) |
| `tool_context.state` | 에이전트 간 데이터 공유 (story_title, story_pages, story_characters) |
| `tool_context.save_artifact` | 생성된 이미지를 ADK Artifact로 저장 |
| `LiteLlm` | ADK에서 OpenAI 모델 사용을 위한 브릿지 |
| `run_in_executor` | 동기 OpenAI 클라이언트를 async 환경에서 블로킹 없이 실행 (병렬 요청) |
| `base64.b64decode` | gpt-image-1 응답(b64_json)을 바이트로 변환 |
| `Pillow(PIL)` | 삽화 위에 한글 동화 텍스트 합성 + 5페이지를 PDF 한 파일로 통합 |
