# AI Manager — Gemini + Claude 멀티에이전트 자동화 시스템

> **Gemini가 두뇌(계획·판단), Claude가 손(실행·검증)** 이 되어  
> 어떤 프로젝트든 처음부터 끝까지 자동으로 완성하는 멀티에이전트 오케스트레이션 시스템.

---

## 핵심 아이디어

AI 하나에게 모든 것을 맡기면 계획도 실행도 모두 같은 모델이 하게 됩니다.  
이 시스템은 **역할을 분리**합니다.

| 역할 | AI | 담당 |
|------|----|------|
| 두뇌 | Gemini | 분석 · 계획 · 판단 · 완료 기준 결정 |
| 손   | Claude | 코드 작성 · 파일 생성 · 자체 검증 · 통합 테스트 |
| 감사 | Codex  | 코드 품질 · 보안 · 버그 독립 검토 |

세 AI가 **서로의 결과를 교차 검토**하기 때문에 단일 AI보다 훨씬 신뢰도 높은 결과물을 냅니다.

---

## 파이프라인

```
INTAKE      Gemini:  사용자 요청 분석 → 프로젝트 유형·핵심 요구사항 파악
CLARIFY     Gemini:  불명확한 부분 질문 → 사용자 답변으로 요구사항 구체화
RESEARCH    Gemini:  기술 스택·접근법·제약 조건 조사
PLAN        Gemini:  작업 분해 · 의존성 설정 · 완료 기준 작성
DISPATCH    Manager: 다음 실행 가능한 작업 선택 (의존성 그래프 해소)
EXECUTE     Claude:  코드·문서·분석 실제 실행
UNIT_VERIFY Claude:  자신의 결과를 스스로 검증 (PASS / FAIL)
DECIDE      Gemini:  계속 / 재시도 / 통합테스트 / 완료 결정
INTEGRATE   Claude:  전체 파일 연결성·동작 가능성 통합 검증
CODEX_REVIEW Codex:  코드 품질·보안·버그 독립 심사
GEMINI_CHECK Gemini: Codex 심사 결과 교차 검증
CLAUDE_RECHECK Claude: 세 AI 검토 결과 최종 교차 검증
INT_REVIEW  Gemini:  최종 판정 → FINISH 또는 수정 작업 생성
FINISH      Manager: 최종 보고서 저장
```

---

## 주요 기능

### 오염 방지 (Contamination Prevention)
Gemini CLI는 `GrepTool`로 로컬 파일을 검색할 수 있습니다.  
이 때 **다른 프로젝트 파일을 읽어 엉뚱한 계획을 세우는 문제**가 발생할 수 있습니다.  
이를 막기 위해 Gemini 호출마다 **빈 임시 격리 디렉토리**를 생성해 CWD로 설정합니다.

```powershell
# 매 Gemini 호출 전
$isoPath = Join-Path $env:TEMP "gemini_iso_$(Get-Date -Format 'yyyyMMddHHmmssff')"
New-Item -ItemType Directory -Path $isoPath -Force | Out-Null
# → GrepTool이 검색해도 아무 파일도 없음
```

추가로 INTAKE 결과에 목표와 무관한 파일 경로가 포함되면 자동으로 감지·재시도합니다.

### PS5.1 직렬화 버그 우회
PowerShell 5.1에서 빈 배열 `@()`는 `ConvertTo-Json` 시 `{}`(빈 오브젝트)로 직렬화됩니다.  
의존성 없는 작업이 `depends_on: {}`로 저장되어 DISPATCH가 영구 실패하는 버그를 `Resolve-Deps` 함수로 중앙 처리합니다.

```powershell
function Resolve-Deps {
    param($raw)
    if ($null -eq $raw)                            { return @() }
    if ($raw -is [string])                         { return @($raw) | Where-Object { $_ -ne "" } }
    if ($raw -is [System.Collections.IEnumerable]) { return @($raw | Where-Object { $_ -is [string] -and $_ -ne "" }) }
    return @()  # PSCustomObject {} → 의존성 없음
}
```

### 디버그 로그 시스템
```
debug_logs/
├── session_YYYYMMDD_HHmmss.log   # 세션 전체 통합 로그
├── LAST_ERROR.log                 # 마지막 오류 (항상 덮어씀)
└── error_YYYYMMDD_HHmmss.log     # 오류 아카이브
```

### GUI 인터페이스
`manager_gui.py` — tkinter 기반 GUI로 터미널 없이 사용 가능.  
실시간 파이프라인 진행 상황, 작업 큐, CLARIFY 단계 대화 지원.

---

## 전제 조건

```powershell
gemini --version   # Gemini CLI  (google-gemini)
claude --version   # Claude Code CLI
codex  --version   # OpenAI Codex CLI
python --version   # GUI 사용 시 (tkinter 포함)
```

---

## 실행 방법

### CLI

```powershell
# 새 프로젝트 — 완료까지 자동 실행
.\manager.ps1 -Goal "FastAPI로 할일 관리 API를 만들어줘" -Auto

# 새 프로젝트 — 한 단계씩
.\manager.ps1 -Goal "React 캘린더 앱 만들기"

# 이어서 실행
.\manager.ps1 -Resume -Auto

# 완성된 프로젝트 수정 요청
.\manager.ps1 -Revise "다크 모드를 추가해줘" -Auto

# 작업 폴더 지정
.\manager.ps1 -Goal "목표" -WorkspaceDir "D:\MyProject" -Auto
```

### GUI

```powershell
python manager_gui.py
```

---

## 파일 구조

```
ai_manager/
├── manager.ps1              ← 메인 스크립트 (상태 머신 + AI 오케스트레이션)
├── manager_gui.py           ← tkinter GUI
├── ROLES.md                 ← 각 AI의 역할 정의
│
│   [자동 생성 — .gitignore 처리]
├── GOAL.md                  ← 사용자 목표
├── INTAKE.md                ← 프로젝트 분석 결과
├── RESEARCH.md              ← 기술 리서치 결과
├── PLAN.md                  ← 전체 계획
├── ACCEPTANCE_CRITERIA.md   ← 완료 기준
├── STATE.json               ← 현재 실행 상태
├── TASK_QUEUE.json          ← 작업 큐 (의존성 그래프)
├── tasks/                   ← 각 작업 지시서
├── results/                 ← 각 작업 실행 결과
├── reviews/                 ← 자체 검증 결과
├── integration/             ← 통합 검증 보고서
├── workspace/               ← 실제 산출물 (코드 등)
└── debug_logs/              ← 오류 로그
```

---

## 안전장치

| 항목 | 기본값 | 위치 |
|------|--------|------|
| 전체 반복 제한 | 30회 | `STATE.json` `max_iterations` |
| 작업별 재시도 | 3회 | `STATE.json` `max_retries_per_task` |
| 자동 통합 주기 | 3작업마다 | `STATE.json` `integrate_every_n` |
| CLI 타임아웃 | 600초 | `manager.ps1` `$TIMEOUT_SEC` |
| AI 출력 자동 실행 | **금지** | 설계 원칙 |
| 파일 수정 위치 | workspace/ 전용 | 프롬프트 규칙 |

---

## 기술 스택

- **PowerShell 5.1** — 상태 머신, AI 오케스트레이션, 파일 I/O
- **Python 3 + tkinter** — GUI
- **Gemini CLI** — 계획·판단 (google-gemini)
- **Claude Code CLI** — 코드 실행·검증 (Anthropic)
- **OpenAI Codex CLI** — 코드 품질·보안 심사

---

## 오류 대응

```
오류 발생 시 확인:
  debug_logs\LAST_ERROR.log

수동 재시작:
  STATE.json의 status 필드를 원하는 단계로 수정 후
  .\manager.ps1 -Resume -Auto
```

---

## License

MIT
