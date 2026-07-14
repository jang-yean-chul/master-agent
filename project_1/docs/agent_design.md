# WordiTale (워디테일) — 에이전트 설계 문서

> 유아 단어 학습용 맞춤 동화 생성 에이전트 · Step 1 설계 (2026-07-09) · Step 3 확장 (2026-07-12)

## 1. 이름

**WordiTale (워디테일)** — Word(단어) + Fairy Tale(동화). 목표 단어를 씨앗 삼아 동화를 엮어내는 에이전트.

## 2. 목적

부모가 고른 **5~10개의 학습 단어**를 자연스럽게 녹여낸 **5~8페이지 분량의 유아용 맞춤 동화 텍스트**를 자동 생성하고, 규칙을 어긴 결과물(단어 누락, 페이지 수 위반, 문장 과다 등)을 스스로 검증·재작성한다. 완성된 텍스트는 이후 단계에서 부모 음성 TTS의 낭독 스크립트로 쓰인다.

**해결하는 문제:** 시중 동화책은 "우리 아이가 지금 배워야 할 단어"에 맞춰져 있지 않다. 부모가 직접 쓰기엔 시간이 없고, LLM에 한 번 시키면 단어 누락·분량 초과가 잦다. → 생성과 검증을 분리한 에이전트로 품질을 보장한다.

## 3. 핵심 기능

| # | 기능 | 설명 |
|---|------|------|
| 1 | 스토리 플래닝 | 단어·연령·테마를 받아 유아 눈높이의 줄거리 개요 생성 |
| 2 | 페이지별 텍스트 생성 | 5~8페이지, 페이지당 1~2문장, 목표 단어를 페이지에 배치 |
| 3 | 자동 검증 + 재작성 루프 | 단어 포함 여부·페이지 수·문장 길이를 규칙 기반 검사, 실패 시 재작성 (최대 N회) |
| 4 | 단어 적합성 검사 (툴①) | 금지어·글자 수·한글 여부를 검사해 부적합 입력은 생성 전에 거절 |
| 5 | 연령별 작문 스타일 | 사용자 입력(나이)에 따라 영아용(≤3세, 의성어 1문장)과 표준(≥4세) 경로 분기 |
| 6 | 삽화 프롬프트 병렬 생성 | Send API로 페이지 수만큼 팬아웃해 페이지별 삽화 지시문을 동시 생성 |
| 7 | 동화책 파일 저장 (툴②) | 완성본(텍스트+삽화 프롬프트)을 output/*.md로 저장 |
| 8 | 아이별 학습 메모리 | 체크포인터 + thread_id로 배운 단어를 누적, 다음 동화에 복습 단어로 반영 |
| 9 | (확장) TTS 스크립트 출력 | 부모 음성 합성 엔진에 넘길 페이지별 낭독 텍스트 포맷 |

※ 부모 음성 학습(voice cloning)은 LLM 그래프가 아닌 별도 음성 서비스 영역 → 이 그래프의 출력(페이지 텍스트)을 입력으로 받는 후속 파이프라인으로 분리.

## 4. 그래프 구조 (워크플로우 3패턴: 체이닝 + Orchestrator-Workers + 병렬)

```
START
  │
  ▼
[check_words]  툴①: 단어 적합성 검사 (금지어/한글/글자수)
  │
  ├─ 부적합 ──▶ [reject_input] 거절 사유 안내 ──▶ END     ◀ 조건부 엣지 ①
  │
  └─ 통과 ──▶ [plan_story]  오케스트레이터
                │   줄거리 + 페이지 수·단어 배치·페이지별 장면(브리프)을 동적 계획
                │
                │  Send 팬아웃 ×N (나이로 워커 종류 선택)   ◀ 조건부 엣지 ② (사용자 입력 분기)
                ├─ child_age ≤ 3 ──▶ [write_page_toddler] ×N  의성어 워커 (병렬)
                └─ child_age ≥ 4 ──▶ [write_page_standard] ×N  스토리 워커 (병렬)
                                        │  (pages는 페이지 번호로 병합되는 리듀서)
                                        ▼
              [validate_story] 규칙 검사 (단어 포함, 페이지 수, 길이) — 체이닝의 게이트
                │
                ├─ 실패 & 재시도 가능 ──▶ 워커 재팬아웃 (루프, 최대 2회)  ◀ 조건부 엣지 ③
                │
                └─ 통과 or 재시도 소진 ──▶ [finalize] 상태 확정 + 배운 단어 메모리 누적
                                             │
                                             ▼ Send API 팬아웃 (페이지 수만큼 병렬)
                                  [gen_illust_prompt] × N  페이지별 삽화 프롬프트
                                             │
                                             ▼
                                  [save_storybook]  툴②: output/*.md 저장
                                             │
                                             ▼
                                            END
```

### 4-1. 브리프 설계 — 병렬 작성에서 문장 연결을 지키는 방법

원칙: **서사는 오케스트레이터가 전부 결정하고, 워커는 자기 장면의 문장만 렌더링한다.**

- 오케스트레이터가 만드는 PageBrief: `{page, role(도입/전개/마무리), scene(장면 한 줄), words(배치 단어)}` — scene은 서로 겹치지 않게 사건 순서대로
- 워커가 받는 것: 전체 줄거리 + 자기 브리프 + **직전/다음 페이지 장면 요약**
- 워커 규칙(중복 방지의 핵심): 앞뒤 장면은 "참고만" — 직전 장면은 이미 쓰였으니 재서술 금지, 다음 장면은 다음 페이지 몫이니 미리 서술 금지. 문체(해요체)와 주인공 지칭(이름만, 수식어 반복 금지)도 통일
- 안전망: 오케스트레이터 출력이 페이지 범위를 벗어나면 규칙 기반 브리프로 대체, 빠뜨린 단어는 마지막 페이지에 자동 배치. 이후 validate_story 게이트가 최종 검증

## 5. State 설계

```python
class StoryState(TypedDict, total=False):
    # 입력
    target_words: list[str]   # 학습 단어 5~10개
    child_age: int            # 아이 나이 → 작문 스타일 분기 (조건부 엣지 ②)
    theme: str                # 테마 (예: 숲속 모험)
    hero: str                 # 주인공 설정 (예: "아기 토끼 토토") — 캐릭터 일관성 기준
    character_sheet: str      # plan_story가 만든 주인공 외형 묘사(영어 1문장)
                              # → 모든 삽화 프롬프트가 이 문장으로 시작 (그림 간 캐릭터 고정)
    page_briefs: list[PageBrief]  # 오케스트레이터의 페이지별 작업 지시서
    # pages: Annotated[list[Page], _merge_pages]
                              # 워커 병렬 결과 — 페이지 번호로 병합 (재작성 시 덮어쓰기)
    # 중간 산출물
    word_check: dict          # check_words 툴 결과 {ok, problems}
    story_plan: str           # plan_story 출력
    pages: list[Page]         # write_pages_* 출력 [{page, text}]
    illust_prompts: Annotated[list[IllustPrompt], _extend_or_reset]
                              # Send 병렬 결과 (리듀서로 병합, None이면 초기화)
    # 검증/제어
    issues: list[str]         # validate_story가 찾은 문제
    retry_count: int          # 재작성 횟수
    status: str               # ok / failed_validation / rejected
    saved_path: str           # save_storybook 툴이 저장한 경로
    # 메모리 (thread별 누적)
    learned_words: Annotated[list[str], _union_words]
                              # 배운 단어 (중복 없이 union, 다음 동화의 복습 단어로 활용)
```

## 5-1. 툴 · 병렬 · 메모리 설계

| 요소 | 구현 | 비고 |
|------|------|------|
| 툴① `check_words` | `@tool` 커스텀 툴 — 개수/한글/길이/금지어 검사 | 생성 전 입력 게이트 |
| 툴② `save_storybook` | `@tool` 파일 툴 — 완성본을 `output/<제목>.md`로 저장 | Step 5 TTS 포맷의 기반 |
| 병렬 (Send API) | ① `plan_story` 뒤 페이지 워커 ×N ② `finalize` 뒤 `Send("gen_illust_prompt", …)` ×N | 페이지 작성은 브리프 기반이라 독립적, 삽화 프롬프트도 페이지 간 독립. 추후 실제 이미지 생성 API 병렬 호출로 재활용 |
| Orchestrator-Workers | `plan_story`가 페이지 수·단어 배치·브리프를 동적 계획 → 워커가 병렬 렌더링 | 브리프 설계는 §4-1 참고 |
| 메모리 | `MemorySaver` 체크포인터 + 아이별 `thread_id` | `learned_words`가 union 리듀서로 누적 → `plan_story`가 복습 단어 1~2개를 다음 동화에 등장시킴 |
| LLM 선택 | `OPENAI_API_KEY` → OpenAI(gpt-4o-mini), `ANTHROPIC_API_KEY` → Claude, 없으면 mock | 그래프 구조 개발/시연은 키 없이 가능 |

## 6. 주요 엣지 케이스 (설계에 반영됨)

1. 단어 수 5개 미만 / 10개 초과 → check_words 툴이 생성 전에 거절
2. 부적합 단어(금지어, 비한글, 과도한 길이) → check_words 툴이 사유와 함께 거절
3. 단어 수(최대 10) > 페이지 수(최대 8) → 한 페이지에 단어 2개 배치 로직
4. 생성문에 목표 단어 누락 → validator가 잡아 재작성 루프
5. 한국어 조사 결합("사과를", "바람이") → 부분 문자열 매칭으로 검출
6. 무한 재작성 → retry_count 상한(2회) 후 경고와 함께 종료
7. 페이지당 텍스트 과다 → 페이지당 최대 글자 수 검사
8. 같은 thread에서 새 동화 생성 → plan_story가 retry_count/issues/illust_prompts를 초기화 (learned_words만 누적 유지)

## 7. 비용 계획 (2026-07 확정)

1. **1차 — 텍스트만 테스트**: gpt-4o-mini 기준 동화 1편 ≈ $0.001, 사실상 무료. 구조 디버깅은 mock 모드로 키 없이.
2. **2차 — 저가 이미지 테스트**: gpt-image 계열 Low 품질(장당 ~$0.011) → 삽화 7장 기준 권당 ~$0.08.
3. **최종 — Medium 품질 출력**: 장당 ~$0.042 → 권당 ~$0.30.
