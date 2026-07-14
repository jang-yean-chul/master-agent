# WordiTale 인수인계 문서

> 최종 갱신: 2026-07-14 · 작성 기준 커밋: `754dfc7` (가족 목소리 등록 기능)

## 1. 프로젝트 개요

**WordiTale (워디테일)** — 부모가 고른 학습 단어 5~10개를 자연스럽게 녹인 5~8페이지 유아 맞춤 동화를 생성하고, 최종적으로 **가족 목소리 TTS로 읽어주는** 유아 교육 서비스의 에이전트 파트.

- 핵심 아이디어: LLM은 "단어를 모두 넣어줘" 같은 제약을 종종 어기므로, **생성과 검증을 분리**하고 검증 실패 시 재작성 루프로 품질을 구조적으로 보장한다.
- 기술 스택: Python 3.11 · LangGraph · Streamlit · OpenAI(gpt-4o-mini) / Anthropic(Claude) 겸용 · mutagen

## 2. 저장소 구조 (⚠️ 중요 — 이중 저장소)

| 저장소 | 역할 |
|--------|------|
| `C:\Users\c\Desktop\Masteragent` (로컬 git 루트, origin=master-agent.git) | 과제 모음 상위 저장소. **project_1이 WordiTale** |
| https://github.com/jang-yean-chul/WordiTale | WordiTale 공개 저장소. project_1만 분리해서 푸시 |

**WordiTale 저장소에 올리는 방법** (Masteragent 루트에서):

```bash
git add project_1        # (+ 필요시 .gitignore)
git commit -m "..."
git subtree split --prefix=project_1 -b worditale-export
git push https://github.com/jang-yean-chul/WordiTale.git worditale-export:main
git branch -D worditale-export
```

subtree split은 결정적(deterministic)이라 매번 이전 히스토리에 이어붙는 fast-forward push가 된다.

## 3. 폴더 구조

```
project_1/
├── app.py                 # Streamlit 대화형 UI (진입점)
├── requirements.txt
├── .env                   # OPENAI_API_KEY (git 제외 — 새 환경에선 직접 생성)
├── .venv/                 # 가상환경 (git 제외)
├── docs/
│   ├── agent_design.md    # 설계 문서 (그래프/State/툴/엣지 케이스/비용 계획)
│   └── HANDOVER.md        # 이 문서
├── src/
│   └── worditale/         # 에이전트 패키지 (의존 방향: config ← state ← llm/tools ← nodes ← graph)
│       ├── __init__.py    #   외부 인터페이스 (graph, check_words, llm_provider 등 re-export)
│       ├── config.py      #   비즈니스 규칙 상수 · 주인공 기본값
│       ├── state.py       #   State(TypedDict) + 리듀서 (_merge_pages, _extend_or_reset, _union_words)
│       ├── llm.py         #   LLM 클라이언트 — 이미지·TTS 클라이언트가 추가될 자리
│       ├── tools.py       #   툴① check_words · 툴② save_storybook
│       ├── nodes.py       #   노드 함수 전부 (오케스트레이터/워커/검증/삽화/저장 + mock 로직)
│       ├── graph.py       #   라우팅(조건부 엣지) + StateGraph 조립 + MemorySaver
│       ├── __main__.py    #   CLI 데모 (`python -m worditale`)
│       └── voice_store.py #   가족 목소리 mp3 저장소
├── output/                # 생성된 동화책 .md (자동 생성, git 제외)
└── voices/                # 가족 목소리 녹음 (자동 생성, 개인정보 — git 제외)
```

파일 분리 원칙(2026-07-14): 이미지(Step 5)·TTS(Step 6) 확장을 앞두고 관심사별로 분리.
nodes/ 하위 패키지·mock 클래스 추상화는 현 규모에선 과설계라 의도적으로 보류 — nodes.py가
400줄을 넘어가면 그때 쪼갠다. app.py(Streamlit)도 목소리 패널이 커지면 ui 모듈로 분리 예정.

## 4. 에이전트 아키텍처 (src/worditale/)

워크플로우 3패턴 조합: **프롬프트 체이닝**(검증 게이트) + **Orchestrator-Workers** + **병렬 처리**(Send).
Supervisor 멀티에이전트는 의도적으로 채택하지 않음 — 절차가 고정된 작업이라 워크플로우가 적합 (2026-07-14 결정).

```
START → check_words(툴①)
  ├─ 부적합 → reject_input → END                      [조건부 엣지 ①]
  └─ 통과 → plan_story (오케스트레이터: 줄거리+페이지별 브리프+캐릭터 시트)
       │  [Send 병렬 ×N — 나이로 워커 선택]              [조건부 엣지 ②: 사용자 입력]
       ├─ age ≤ 3 → write_page_toddler ×N (의성어 워커)
       └─ age ≥ 4 → write_page_standard ×N (스토리 워커)
            → validate_story ↔ 재작성 루프: 워커 재팬아웃 (최대 2회)  [조건부 엣지 ③]
            → finalize → [Send 병렬 ×N] gen_illust_prompt
            → save_storybook(툴②) → END
```

핵심 개념:

- **Orchestrator-Workers + 브리프 설계**: plan_story가 페이지 수·단어 배치·페이지별 장면(PageBrief)을 동적으로 계획. 각 워커는 (전체 줄거리 + 자기 브리프 + 앞뒤 장면 요약)을 받아 자기 장면만 렌더링 — 앞뒤 장면은 "참고만"(재서술·선행 서술 금지 규칙)이라 병렬로 써도 중복·모순이 없음. `pages`는 페이지 번호로 병합하는 리듀서(`_merge_pages`)라 재작성 루프에서 같은 페이지를 덮어씀. 안전망: 오케스트레이터가 페이지 수 범위를 벗어나면 규칙 기반 브리프로 대체, 누락 단어는 마지막 페이지에 자동 배치
- **툴 2개** (`@tool`): `check_words`(금지어/한글/글자수/개수 검사), `save_storybook`(output/*.md 저장)
- **메모리**: `MemorySaver` + `thread_id`(아이 이름별). `learned_words`가 union 리듀서로 누적 → plan_story가 복습 단어 1~2개를 다음 동화에 등장시킴
- **캐릭터 일관성**: `hero`(주인공 설정, 기본 "아기 토끼 토토") → plan_story가 `character_sheet`(영어 외형 1문장)를 만들고, **모든 삽화 프롬프트가 이 문장으로 시작**. 본문은 주인공 이름으로만 지칭('유아/아이' 금지)
- **Send 병렬**: finalize 뒤 페이지 수만큼 `gen_illust_prompt` 팬아웃. `illust_prompts`는 `_extend_or_reset` 리듀서 — 병렬 결과는 이어붙이고 `None`을 주면 초기화(같은 thread에서 새 동화 시작 시 plan_story가 초기화)
- **LLM 선택**: `OPENAI_API_KEY` → gpt-4o-mini, `ANTHROPIC_API_KEY` → claude-sonnet-4-5, 둘 다 없으면 **mock**(규칙 기반) — 키 없이 전체 그래프 개발/시연 가능
- `demo_fail_first`: mock 전용 데모 플래그. 첫 시도에 단어를 일부러 빼서 재작성 루프를 시연
- ⚠️ mock 강제 방법: PowerShell의 `$env:KEY=''`는 변수를 **삭제**해서 dotenv가 .env의 실제 키를 로드해버림. 파이썬 안에서 `os.environ["OPENAI_API_KEY"] = ""`로 빈 문자열을 넣어야 확실함 (dotenv는 기존 변수를 덮어쓰지 않음)

## 5. Streamlit 앱 (app.py)

- **채팅 플로우**: stage 상태머신 `words → age → theme → (생성) → words`. 세션 상태 `messages`(대화 기록), `pending`(수집 중 입력)
- **실행 시각화**: `graph.stream(inputs, config, stream_mode="updates")`로 노드 실행을 st.status에 실시간 표시, 완료 후 각 메시지의 "실행 과정" expander로 보존
- **그래프 시각화**: `graph.get_graph().draw_mermaid()` → mermaid CDN을 쓰는 HTML을 임시 파일로 만들어 `st.iframe`으로 표시 (오프라인이면 다이어그램만 안 뜸, 앱은 정상)
- **이용 가이드**: 상단 expander, 첫 방문(메시지 1개 이하) 시 자동 펼침
- **목소리 등록**: 역할(엄마/아빠/할아버지/할머니) 선택 → mp3 업로드 → `voice_store.save_sample` 검증·저장. 업로더 key에 `upload_nonce`를 써서 저장 후 초기화(중복 저장 방지), 결과 메시지는 `voice_msgs` 세션 키로 rerun 후 표시
- 사이드바: 아이 이름(=thread_id), 주인공 캐릭터, 배운 단어 수, 대화 초기화

## 6. voice_store (TTS 준비)

- 역할별 `voices/<역할>/sample_N.mp3` 최대 **2개**, mutagen으로 길이 검증 (허용 30초~5분, **권장 2분**)
- 결정 배경: ElevenLabs Instant Voice Cloning은 1~3분 샘플이면 충분 (3분 초과는 오히려 비권장). 부모가 부담 없이 녹음할 수 있는 최소 요구로 설계
- ⚠️ 목소리는 개인정보 — `voices/`는 절대 커밋 금지 (.gitignore 처리됨)

## 7. 실행 & 테스트

```bash
cd project_1
.venv\Scripts\activate            # 없으면: python -m venv .venv 후 pip install -r requirements.txt
streamlit run app.py              # 대화형 앱
cd src; python -m worditale       # CLI 데모 (3개 시나리오: 재작성 루프/나이 분기·메모리/거절)
```

- `.env`에 `OPENAI_API_KEY=...` 있으면 실제 생성, 없으면 mock. **app.py와 CLI 둘 다 .env 자동 로딩**
- Windows 콘솔 인코딩 문제 시 `$env:PYTHONUTF8=1` 설정 후 실행
- VSCode에서 import 경고가 뜨면 인터프리터를 `project_1/.venv`로 선택
- **테스트 방법** (정식 테스트 폴더는 아직 없음 — 필요 시 tests/로 승격 권장):
  - 앱 플로우: `streamlit.testing.v1.AppTest`로 채팅 시나리오 자동화 (거절→단어→나이→테마→생성→메모리). mock 강제하려면 `OPENAI_API_KEY=''`(빈 값)로 실행 — dotenv는 기존 환경변수를 덮어쓰지 않음
  - voice_store: mp3 프레임을 코드로 합성(`b"\xff\xfb\x90\xc0" + b"\x00"*413` × N프레임)해 길이 검증까지 테스트 가능

## 8. 진행 상태 & 로드맵

| 단계 | 상태 |
|------|------|
| Step 1 설계 / Step 2 LangGraph 기초 | ✅ |
| Step 3 툴 2개 · 나이 분기 · Send 병렬 · 메모리 | ✅ |
| Step 4 실제 API 텍스트 품질 (캐릭터 일관성 포함) | ✅ 1차 통과 (2026-07-13, 6/6 삽화 프롬프트 일관성 확인) |
| Streamlit 대화형 UI + 이용 가이드 + 목소리 등록 | ✅ |
| **Step 5 삽화 이미지 생성** | ⬜ 다음 후보. 확정된 비용 계획: 테스트는 Low 품질(장당 ~$0.011) → 최종 Medium(장당 ~$0.042, 권당 ~$0.30). gpt-image-1은 2026-10 종료 예정이라 gpt-image-1.5/2 사용 권장 |
| **Step 6 부모 음성 TTS** | 🟡 샘플 업로드까지 완료. 다음: ElevenLabs IVC로 클로닝 → 페이지별 낭독 mp3 생성 → st.audio 재생. 권장 순서: 기본 보이스로 파이프라인 먼저 → 클로닝 교체 |
| Step 7 앱 UI 완성/배포 | ⬜ Streamlit 배포 예정 |

## 9. 알려진 제약 & 주의사항

1. **메모리 휘발성**: `MemorySaver`는 프로세스 메모리 — 서버 재시작 시 배운 단어가 사라짐. 배포 전 `SqliteSaver`(langgraph-checkpoint-sqlite)로 교체 필요
2. **LLM JSON 파싱**: write 노드가 `re.search(r"\[.*\]")`로 JSON을 추출 — 모델이 형식을 어기면 예외 발생 가능. 실패 시 재시도 로직은 아직 없음
3. **mermaid 다이어그램**은 CDN 로드라 오프라인에서 안 보임 (기능엔 영향 없음)
4. **비용**: 텍스트는 권당 ~$0.001로 무시 가능. 이미지 붙이면 권당 수백 원대 — 테스트는 반드시 Low 품질로
5. 과제 요건 매핑(노드 9개, 조건부 엣지 3개, 툴 2개, Send 병렬, 메모리)은 README의 표 참고

## 10. 참고 링크

- WordiTale 저장소: https://github.com/jang-yean-chul/WordiTale
- 설계 문서: [agent_design.md](agent_design.md)
- 같은 상위 저장소의 참고 프로젝트: `study/restaurant-bot`(Streamlit 채팅 패턴 원본), `study/storybook_agent`(Vertex AI ADK — Streamlit 아님)
- ElevenLabs 음성 클로닝: https://elevenlabs.io/docs/eleven-creative/voices/voice-cloning
