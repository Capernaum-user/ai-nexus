#Requires -Version 5.1
<#
.SYNOPSIS
    Gemini(두뇌) + Claude(손) 이중 구조 AI 중앙관리자
.DESCRIPTION
    - Gemini: 문제 분석, 리서치, 계획 수립, 판단, 완료 판정
    - Claude: 코드/문서/분석 실행, 자체 검증, 통합 테스트, 오류 분석
    - 상태: INTAKE → RESEARCH → PLAN → DISPATCH → EXECUTE
              → UNIT_VERIFY → DECIDE → INTEGRATE → INT_REVIEW → FINISH
#>

param(
    [string]$Goal         = "",
    [string]$Revise       = "",
    [string]$WorkspaceDir = "",   # 사용자 지정 작업 폴더 (비어있으면 기본 workspace/ 사용)
    [switch]$Resume,
    [switch]$Step,
    [switch]$Auto,
    [switch]$Help,
    [switch]$GUI
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# 미처리 예외 전역 트랩 → debug_logs/LAST_ERROR.log 기록
trap {
    $errLine = try { $_.InvocationInfo.ScriptLineNumber } catch { "?" }
    $errMsg  = $_.Exception.Message
    $stack   = try { $_.ScriptStackTrace } catch { "" }
    $full    = "UNHANDLED EXCEPTION at line ${errLine}: ${errMsg}`n${stack}"
    Write-Log $full -Level "ERROR"
    break
}

# ── 경로 ────────────────────────────────────────────────────
$script:ROOT        = $PSScriptRoot
$script:TASKS_DIR   = Join-Path $ROOT "tasks"
$script:RESULTS_DIR = Join-Path $ROOT "results"
$script:REVIEWS_DIR = Join-Path $ROOT "reviews"
$script:LOGS_DIR    = Join-Path $ROOT "logs"
$script:WORKSPACE   = Join-Path $ROOT "workspace"
$script:INTEG_DIR   = Join-Path $ROOT "integration"

$script:GOAL_FILE      = Join-Path $ROOT "GOAL.md"
$script:INTAKE_FILE    = Join-Path $ROOT "INTAKE.md"
$script:CLARIFY_FILE        = Join-Path $ROOT "CLARIFICATIONS.md"
$script:CLARIFY_QUEST_FILE  = Join-Path $ROOT "CLARIFY_QUESTIONS.md"
$script:RESEARCH_FILE       = Join-Path $ROOT "RESEARCH.md"
$script:DEEP_RESEARCH_FILE  = Join-Path $ROOT "DEEP_RESEARCH.md"
$script:HALLCHECK_FILE      = Join-Path $ROOT "HALLCHECK.md"
$script:PLAN_FILE      = Join-Path $ROOT "PLAN.md"
$script:CRITERIA_FILE  = Join-Path $ROOT "ACCEPTANCE_CRITERIA.md"
$script:REVISE_FILE    = Join-Path $ROOT "REVISIONS.md"
$script:STATE_FILE     = Join-Path $ROOT "STATE.json"
$script:QUEUE_FILE     = Join-Path $ROOT "TASK_QUEUE.json"
$script:INTEG_REPORT   = Join-Path $ROOT "integration\INTEGRATION_REPORT.md"

$script:TIMEOUT_SEC    = 600
$script:MAX_PARALLEL   = 10    # 동시 실행 최대 워커 수
$script:GUI            = $GUI.IsPresent
$script:DEBUG_DIR      = Join-Path $ROOT "debug_logs"
$script:SESSION_LOG    = ""   # Ensure-Dirs 에서 설정

# 사용자 지정 작업 폴더 처리
if ($WorkspaceDir) {
    if (-not (Test-Path $WorkspaceDir)) {
        New-Item -ItemType Directory -Path $WorkspaceDir -Force | Out-Null
    }
    $script:WORKSPACE = $WorkspaceDir
}

# GUI 모드: 콘솔 출력 인코딩 강제 UTF-8
if ($script:GUI) {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding            = [System.Text.Encoding]::UTF8
}

# ── 유틸 ────────────────────────────────────────────────────

function Write-Log {
    param([string]$Msg, [ValidateSet("INFO","WARN","ERROR")][string]$Level = "INFO")
    $ts   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts][$Level] $Msg"
    $color = @{ INFO="White"; WARN="Yellow"; ERROR="Red" }[$Level]
    Write-Host $line -ForegroundColor $color
    $main = Join-Path $script:LOGS_DIR "manager.log"
    if (Test-Path $script:LOGS_DIR) { Add-Content -Path $main -Value $line -Encoding UTF8 }
    # 세션 통합 로그 (debug_logs/session_*.log)
    if ($script:SESSION_LOG -and $script:SESSION_LOG -ne "") {
        try { Add-Content -Path $script:SESSION_LOG -Value $line -Encoding UTF8 } catch {}
    }
    # ERROR → debug_logs/LAST_ERROR.log + error_TIMESTAMP.log
    if ($Level -eq "ERROR" -and $script:DEBUG_DIR -and (Test-Path $script:DEBUG_DIR)) {
        $tsFile   = Get-Date -Format "yyyyMMdd_HHmmss"
        $stateStr = try { if (Test-Path $script:STATE_FILE) { [IO.File]::ReadAllText($script:STATE_FILE,[Text.Encoding]::UTF8) } else { "(없음)" } } catch { "(읽기 실패)" }
        $errBody  = "[$ts] ERROR: $Msg`n`n=== STATE.json ===`n$stateStr`n"
        try {
            [IO.File]::WriteAllText((Join-Path $script:DEBUG_DIR "LAST_ERROR.log"),       $errBody, [Text.Encoding]::UTF8)
            [IO.File]::WriteAllText((Join-Path $script:DEBUG_DIR "error_${tsFile}.log"), $errBody, [Text.Encoding]::UTF8)
        } catch {}
    }
}

function Read-Json  { param([string]$p)
    try   { [System.IO.File]::ReadAllText($p,[Text.Encoding]::UTF8) | ConvertFrom-Json }
    catch {
        $e = Join-Path $script:LOGS_DIR "json_err_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
        try { [System.IO.File]::ReadAllText($p,[Text.Encoding]::UTF8) | Out-File $e -Encoding UTF8 } catch {}
        throw "JSON 파싱 실패: $p → 원본: $e"
    }
}

function Write-Json { param([string]$p, [object]$d, [int]$depth=10)
    [System.IO.File]::WriteAllText($p, ($d|ConvertTo-Json -Depth $depth), [Text.Encoding]::UTF8)
}

function Read-File  { param([string]$p)
    if (Test-Path $p) { [System.IO.File]::ReadAllText($p,[Text.Encoding]::UTF8) } else { "" }
}

function Write-File { param([string]$p, [string]$c)
    [System.IO.File]::WriteAllText($p, $c, [Text.Encoding]::UTF8)
}

function Test-Cmd { param([string]$n)
    try { $null = Get-Command $n -ErrorAction Stop; $true } catch { $false }
}

function Stop-Fail {
    param([string]$reason)
    Write-Log $reason -Level "ERROR"
    $fl = Join-Path $script:LOGS_DIR "FAILED.log"
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') FAILED: $reason" | Out-File $fl -Append -Encoding UTF8
    if (Test-Path $script:STATE_FILE) {
        try { $s = Read-Json $script:STATE_FILE; $s.status = "FAILED"; Write-Json $script:STATE_FILE $s } catch {}
    }
    Write-Host "`n=== FAILED ===" -ForegroundColor Red
    Write-Host "사유: $reason" -ForegroundColor Red
    Write-Host "로그: $fl" -ForegroundColor Yellow
    Write-Host "디버그: $(Join-Path $script:DEBUG_DIR 'LAST_ERROR.log')" -ForegroundColor Yellow
    exit 1
}

function Ensure-Dirs {
    @($script:TASKS_DIR,$script:RESULTS_DIR,$script:REVIEWS_DIR,
      $script:LOGS_DIR,$script:WORKSPACE,$script:INTEG_DIR,$script:DEBUG_DIR) | ForEach-Object {
        if (-not (Test-Path $_)) { New-Item -ItemType Directory -Path $_ -Force | Out-Null }
    }
    # 세션 로그 파일 초기화 (아직 설정되지 않은 경우에만)
    if ($script:SESSION_LOG -eq "") {
        $ts = Get-Date -Format "yyyyMMdd_HHmmss"
        $script:SESSION_LOG = Join-Path $script:DEBUG_DIR "session_${ts}.log"
        $header = "=== AI Manager Session Start: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===`nGoal: $(if(Test-Path $script:GOAL_FILE){[IO.File]::ReadAllText($script:GOAL_FILE,[Text.Encoding]::UTF8)}else{'(미설정)'})`n"
        try { [IO.File]::WriteAllText($script:SESSION_LOG, $header, [Text.Encoding]::UTF8) } catch {}
    }
}

function Update-State { param([hashtable]$u)
    $s = if (Test-Path $script:STATE_FILE) { Read-Json $script:STATE_FILE }
         else { New-DefaultState }
    foreach ($k in $u.Keys) { $s.$k = $u[$k] }
    Write-Json $script:STATE_FILE $s
    Write-Log "STATE: $($u.Keys -join ', ') 업데이트"
}

function New-DefaultState {
    [PSCustomObject]@{
        status               = "INTAKE"
        project_type         = "unknown"
        current_task_id      = $null
        iteration            = 0
        max_iterations       = 30
        max_retries_per_task = 3
        integrate_every_n    = 3
        tasks_since_integrate= 0
        is_complete          = $false
        last_agent           = $null
        last_result_file     = $null
        last_review_file     = $null
    }
}

# ── CLI 실행 (Gemini / Claude / Codex) ───────────────────

# ── AI 비동기 시작 (병렬 실행 지원) ─────────────────────────

function Start-AIJob {
    param(
        [ValidateSet("gemini","claude","codex")][string]$Agent,
        [string]$Prompt,
        [string]$LogTag = "",
        [switch]$AllowTools   # Gemini 도구 사용 허용 (DEEP_RESEARCH 전용)
    )

    $ts  = Get-Date -Format "yyyyMMdd_HHmmss"
    $pf  = Join-Path $script:LOGS_DIR "prompt_${ts}_${Agent}.txt"
    Write-File $pf $Prompt

    if ($Agent -eq "gemini" -and -not $AllowTools) {
        $noToolPreamble = @"
[CRITICAL SYSTEM INSTRUCTION — HIGHEST PRIORITY — DO NOT IGNORE]
YOU MUST NOT USE ANY TOOLS. ZERO EXCEPTIONS.
- Do NOT call: grep, GrepTool, read_file, write_file, bash, ls, WebSearch, or ANY tool
- Do NOT access the filesystem or read any files
- The workspace directory may contain files from a COMPLETELY DIFFERENT unrelated project — IGNORE them entirely
- Read ONLY the text written in this prompt and respond with TEXT ONLY, immediately
- If you feel the urge to search or read a file, STOP and answer from the prompt text alone

[최우선 시스템 명령 — 반드시 준수]
어떤 도구도 호출하지 마라. grep, GrepTool, 파일 읽기/쓰기, bash, 웹 검색 전부 금지.
파일 시스템 접근 완전 금지. 워크스페이스의 기존 파일은 다른 프로젝트 것이므로 무시하라.
이 프롬프트에 적힌 텍스트만 근거로 즉시 텍스트로만 응답하라.

"@
        $Prompt = $noToolPreamble + $Prompt + "`n`n[REMINDER: TEXT RESPONSE ONLY. DO NOT USE ANY TOOLS.]"
    }

    $cliFlags = switch ($Agent) {
        "gemini" { @("--yolo") }
        "claude" { @("--dangerously-skip-permissions", "-p") }
        "codex"  { @("exec", "--dangerously-bypass-approvals-and-sandbox",
                     "-s", "danger-full-access", "--skip-git-repo-check",
                     "-C", $script:WORKSPACE, "-") }
    }

    $of  = Join-Path $script:LOGS_DIR "output_${ts}_${Agent}$(if($LogTag){"_$LogTag"}).txt"
    $geminiIsoDir = $null
    $jobCwd = switch ($Agent) {
        "gemini" {
            $isoPath = Join-Path $env:TEMP "gemini_iso_$(Get-Date -Format 'yyyyMMddHHmmssff')"
            New-Item -ItemType Directory -Path $isoPath -Force | Out-Null
            $geminiIsoDir = $isoPath
            $isoPath
        }
        "claude" { $script:WORKSPACE }
        default  { $null }
    }

    $cmd = $Agent
    $job = Start-Job -ScriptBlock {
        param($c, $flags, $outFile, $promptText, $cwd)
        try {
            if ($cwd -and (Test-Path $cwd)) { Set-Location $cwd }
            [Console]::InputEncoding  = [Text.Encoding]::UTF8
            [Console]::OutputEncoding = [Text.Encoding]::UTF8
            $result = $promptText | & $c @flags 2>&1
            $text   = $result | Out-String
            [IO.File]::WriteAllText($outFile, $text, [Text.Encoding]::UTF8)
            return $text
        } catch {
            $err = "ERROR: $_"
            [IO.File]::WriteAllText($outFile, $err, [Text.Encoding]::UTF8)
            return $err
        }
    } -ArgumentList $cmd, $cliFlags, $of, $Prompt, $jobCwd

    Write-Log "[$Agent] 시작 (job=$($job.Id)) LogTag=$LogTag"
    return @{
        Job          = $job
        Agent        = $Agent
        OutFile      = $of
        LogTag       = $LogTag
        StartTime    = Get-Date
        GeminiIsoDir = $geminiIsoDir
    }
}

# ── AI job 완료 대기 + 결과 수집 ─────────────────────────────

function Await-AIJob {
    param([hashtable]$Ji, [bool]$Spinner = $true)

    $Agent = $Ji.Agent
    $sw    = [System.Diagnostics.Stopwatch]::StartNew()
    $timedOut = $false

    if ($Spinner) {
        $agentColor = @{ gemini="Cyan"; claude="Green"; codex="Magenta" }[$Agent]
        if (-not $agentColor) { $agentColor = "White" }
        $spinChars = @("|", "/", "-", "\"); $si = 0
        while ($true) {
            Start-Sleep -Milliseconds 500
            $elSec = [int]$sw.Elapsed.TotalSeconds
            $spin  = $spinChars[$si % 4]; $si++
            $tout  = $script:TIMEOUT_SEC
            Write-Host ("`r__SPINNER__:${Agent}:${elSec}:${tout}:${spin}   ") -NoNewline -ForegroundColor $agentColor
            if ($Ji.Job.State -ne "Running") { break }
            if ($sw.Elapsed.TotalSeconds -ge $script:TIMEOUT_SEC) { $timedOut = $true; break }
        }
        Write-Host ""
    } else {
        # 병렬 모드: 스피너 없이 완료까지 대기
        while ($Ji.Job.State -eq "Running") {
            if ($sw.Elapsed.TotalSeconds -ge $script:TIMEOUT_SEC) { $timedOut = $true; break }
            Start-Sleep -Milliseconds 300
        }
    }

    $sw.Stop()

    if ($timedOut) {
        Stop-Job  $Ji.Job -ErrorAction SilentlyContinue
        Remove-Job $Ji.Job -ErrorAction SilentlyContinue
        if ($Ji.GeminiIsoDir -and (Test-Path $Ji.GeminiIsoDir)) {
            Remove-Item $Ji.GeminiIsoDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        Stop-Fail "[$Agent] timeout (${script:TIMEOUT_SEC}초)"
    }

    Remove-Job $Ji.Job -ErrorAction SilentlyContinue

    if ($Ji.GeminiIsoDir -and (Test-Path $Ji.GeminiIsoDir)) {
        Remove-Item $Ji.GeminiIsoDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    $out = if (Test-Path $Ji.OutFile) {
        [IO.File]::ReadAllText($Ji.OutFile, [Text.Encoding]::UTF8)
    } else { "" }

    if ($Agent -eq "gemini" -and $out) {
        $noisePatterns = @(
            'Ripgrep is not available', '\[LocalAgentExecutor\]',
            'Falling back to GrepTool', 'NativeCommandError',
            'FullyQualifiedErrorId', 'CategoryInfo\s*:',
            'At C:\\Users\\.*gemini\.ps1'
        )
        $origLen    = $out.Length
        $cleanLines = $out -split "`n" | Where-Object {
            $ln = $_; $keep = $true
            foreach ($pat in $noisePatterns) { if ($ln -match $pat) { $keep = $false; break } }
            $keep
        }
        $out = $cleanLines -join "`n"
        if ($out.Length -lt $origLen - 20) {
            Write-Log "[$Agent] 노이즈 제거 (${origLen}→$($out.Length) 바이트)" -Level "WARN"
        }
    }

    if ($script:SESSION_LOG -and $script:SESSION_LOG -ne "") {
        $elapsed2 = "{0:mm\:ss}" -f $sw.Elapsed
        $entry = "`n--- [$Agent][$($Ji.LogTag)] $(Get-Date -Format 'yyyyMMdd_HHmmss')  elapsed=$elapsed2  output=$($Ji.OutFile) ---`n"
        try { Add-Content -Path $script:SESSION_LOG -Value $entry -Encoding UTF8 } catch {}
    }

    $elapsed2 = "{0:mm\:ss}" -f $sw.Elapsed
    Write-Log "[$Agent] 완료 (${elapsed2}, $([Math]::Round($out.Length/1KB,1))KB) → $($Ji.OutFile)"
    return $out
}

# ── 단일 호출용 wrapper (기존 코드 호환) ─────────────────────

function Invoke-AI {
    param(
        [ValidateSet("gemini","claude","codex")][string]$Agent,
        [string]$Prompt,
        [string]$LogTag = "",
        [switch]$AllowTools
    )
    Write-Log "[$Agent] 호출 시작..."
    $ji = Start-AIJob -Agent $Agent -Prompt $Prompt -LogTag $LogTag -AllowTools:$AllowTools
    return Await-AIJob -Ji $ji -Spinner $true
}

# ── 마커 추출 ────────────────────────────────────────────

function Get-Section {
    param([string]$text, [string]$start, [string]$end)
    $si = $text.IndexOf($start); $ei = $text.IndexOf($end)
    if ($si -ge 0 -and $ei -gt $si) {
        $text.Substring($si + $start.Length, $ei - $si - $start.Length)
    } else { $null }
}

# ── TASK_QUEUE 정규화 ─────────────────────────────────────

function Resolve-Deps {
    # PS5.1에서 빈 JSON 배열 [] → ConvertTo-Json 시 {} (빈 오브젝트) 로 직렬화되는 버그 우회
    # 입력: null / "" / [] / {} / "TASK-001" / @("TASK-001","TASK-002")
    # 출력: 문자열 ID 만 담은 배열. 없으면 @()
    param($raw)
    if ($null -eq $raw)                                     { return @() }
    if ($raw -is [string])                                  { return @($raw) | Where-Object { $_ -ne "" } }
    if ($raw -is [System.Collections.IEnumerable]) {
        return @($raw | Where-Object { $_ -is [string] -and $_ -ne "" })
    }
    # PSCustomObject {} (빈 오브젝트) 등 나머지 → 의존성 없음
    return @()
}

function Normalize-Queue { param([object]$raw)
    $agentMap = @{ "claude code"="claude"; "claude"="claude";
                   "gemini"="gemini"; "gemini-worker"="gemini";
                   "codex"="codex" }
    $tasks = foreach ($t in $raw.tasks) {
        $a   = "$($t.agent)".ToLower().Trim()
        $agent = if ($agentMap[$a]) { $agentMap[$a] } else { "claude" }
        $rawDep = if ($t.PSObject.Properties["depends_on"])     { $t.depends_on   }
                  elseif ($t.PSObject.Properties["dependencies"]) { $t.dependencies }
                  else { $null }
        $deps = Resolve-Deps $rawDep
        # PS5.1 직렬화 안전: 빈 배열은 $null 로 저장 (ConvertTo-Json {} 버그 방지)
        $depsStore = if ($deps.Count -gt 0) { $deps } else { $null }
        $title = if ($t.PSObject.Properties["title"])       { $t.title }
                 elseif ($t.PSObject.Properties["description"]) { $t.description }
                 else { "(제목 없음)" }
        [PSCustomObject]@{
            id          = $t.id
            title       = $title
            agent       = $agent
            status      = if ($t.PSObject.Properties["status"]) { $t.status } else { "pending" }
            retry_count = if ($t.PSObject.Properties["retry_count"]) { $t.retry_count } else { 0 }
            depends_on  = $depsStore
            instruction = if ($t.PSObject.Properties["instruction"]) { $t.instruction }
                          elseif ($t.PSObject.Properties["description"]) { $t.description }
                          else { "" }
            is_integration_task = $false
        }
    }
    [PSCustomObject]@{ tasks = @($tasks) }
}

function Get-NextTask {
    $q = Read-Json $script:QUEUE_FILE
    foreach ($t in $q.tasks) {
        if ($t.status -ne "pending") { continue }
        $ok = $true
        $depsList = Resolve-Deps $t.depends_on
        foreach ($d in $depsList) {
            $dep = $q.tasks | Where-Object { $_.id -eq $d }
            if (-not $dep -or $dep.status -ne "done") { $ok = $false; break }
        }
        if ($ok) { return $t }
    }
    return $null
}

function Set-TaskStatus { param([string]$id, [string]$status, [int]$retryInc=0)
    $q = Read-Json $script:QUEUE_FILE
    foreach ($t in $q.tasks) {
        if ($t.id -eq $id) {
            $t.status = $status
            if ($retryInc -gt 0) { $t.retry_count += $retryInc }
            break
        }
    }
    Write-Json $script:QUEUE_FILE $q
    Write-Log "TASK $id → $status"
}

function Add-Task { param([string]$id,[string]$title,[string]$agent,[string]$instr,[string[]]$deps=@())
    $q = Read-Json $script:QUEUE_FILE
    $list = [Collections.ArrayList]@($q.tasks)
    # PS5.1 직렬화 안전: 빈 배열 @() → ConvertTo-Json이 {} 로 직렬화하는 버그 방지
    $depsClean = Resolve-Deps $deps
    $depsStore = if ($depsClean.Count -gt 0) { $depsClean } else { $null }
    $list.Add([PSCustomObject]@{
        id=$id; title=$title; agent=$agent; status="pending"
        retry_count=0; depends_on=$depsStore; instruction=$instr; is_integration_task=$false
    }) | Out-Null
    $q.tasks = $list.ToArray()
    Write-Json $script:QUEUE_FILE $q
    Write-Log "새 작업 추가: $id - $title"
}

function Get-NewTaskId {
    $q = Read-Json $script:QUEUE_FILE
    $max = ($q.tasks | ForEach-Object {
        if ($_.id -match 'TASK-(\d+)') { [int]$Matches[1] } else { 0 }
    } | Measure-Object -Max).Maximum
    "TASK-{0:D3}" -f ($max + 1)
}

# 의존성이 모두 완료된 pending 작업 목록 반환 (병렬 실행용)
function Get-ReadyTasksList {
    $q       = Read-Json $script:QUEUE_FILE
    $doneIds = @($q.tasks | Where-Object { $_.status -eq "done" } | ForEach-Object { $_.id })
    return @($q.tasks | Where-Object {
        $t = $_
        if ($t.status -ne "pending") { return $false }
        $deps = @(Resolve-Deps $t.depends_on)
        foreach ($d in $deps) { if ($d -notin $doneIds) { return $false } }
        return $true
    })
}

# 작업 지시서 파일 생성 (tasks/ 에 저장)
function Build-TaskInstructionFile { param($task)
    $tf       = Join-Path $script:TASKS_DIR "$($task.id).md"
    $goal     = Read-File $script:GOAL_FILE
    $research = if (Test-Path $script:RESEARCH_FILE) { Read-File $script:RESEARCH_FILE } else { "" }
    $criteria = if (Test-Path $script:CRITERIA_FILE) { Read-File $script:CRITERIA_FILE } else { "" }
    Write-File $tf @"
# 작업 지시서: $($task.id)

## 제목
$($task.title)

## 지시 내용
$($task.instruction)

## workspace 경로
$script:WORKSPACE

## 전체 목표
$goal

## 리서치 결과
$research

## 완료 기준
$criteria

## 주의
- 파일 생성·수정은 반드시 위 workspace 경로($script:WORKSPACE) 내에서만 한다.
- 상대 경로 금지. 절대 경로를 사용한다.
- 작업 완료 후 변경 파일 목록, 실행 방법, 자체 검증 결과를 요약한다.
- 보안 취약점을 만들지 않는다.
"@
    return $tf
}

# 실행 프롬프트 생성
function Build-ExecutePrompt-Parallel { param($task, $taskFilePath)
    $taskTxt   = Read-File $taskFilePath
    $agentRole = switch ($task.agent) {
        "gemini" { "Gemini 워커이며 분석·설계·문서화를 담당한다." }
        "codex"  { "Codex이며 코드 구현을 담당한다." }
        default  { "Claude이며 코드 작성·파일 생성·구현을 담당한다." }
    }
    return @"
너는 $agentRole

작업 지시서:
$taskTxt

수행 지침:
- 파일 생성·수정 경로: $script:WORKSPACE
- 반드시 위 경로 내에서만 파일을 만든다. 절대 경로를 사용한다.
- 실제로 동작하는 완성본을 만든다.

===RESULT_START===
## 완료된 작업
(무엇을 했는지)

## 생성/수정한 파일
- (파일 경로 목록)

## 실행 방법
(어떻게 실행하는지)

## 자체 검증
(내가 확인한 것들)
===RESULT_END===
"@
}

# 검증 프롬프트 생성
function Build-VerifyPrompt-Parallel { param($task, $resultOut)
    $taskTxt  = if (Test-Path (Join-Path $script:TASKS_DIR "$($task.id).md")) {
        Read-File (Join-Path $script:TASKS_DIR "$($task.id).md")
    } else { $task.instruction }
    $criteria = if (Test-Path $script:CRITERIA_FILE) { Read-File $script:CRITERIA_FILE } else { "" }
    return @"
너는 Claude이며 방금 수행된 작업의 결과를 검증한다.

작업 지시서:
$taskTxt

작업 결과:
$resultOut

전체 완료 기준:
$criteria

검증 항목:
1. 작업 지시서의 요구사항을 모두 수행했는가?
2. 생성한 코드/파일이 실제로 동작할 것인가?
3. 보안 취약점이나 명백한 버그가 있는가?

===VERIFY_START===
## Verdict
PASS 또는 FAIL

## 확인된 문제
- (없으면 "없음")

## 수정 필요 사항
- (FAIL인 경우 구체적으로)
===VERIFY_END===
"@
}

# ── 병렬 실행 엔진 ────────────────────────────────────────────

function Run-ParallelExecute {
    $st         = Read-Json $script:STATE_FILE
    $maxRet     = $st.max_retries_per_task
    $maxWorkers = $script:MAX_PARALLEL

    Write-Log "━━ PARALLEL_EXECUTE: 최대 ${maxWorkers}개 동시 실행 ━━"

    # 활성 워커: ArrayList of @{Task=; Ji=(Start-AIJob 반환값)}
    $workers = [System.Collections.ArrayList]::new()

    while ($true) {

        # ── 1. 완료된 워커 수집 (반복 중 제거 방지 위해 별도 수집) ──
        $completedWorkers = [System.Collections.ArrayList]::new()
        foreach ($w in $workers) {
            if ($w.Ji.Job.State -ne "Running") { [void]$completedWorkers.Add($w) }
        }

        foreach ($w in $completedWorkers) {
            [void]$workers.Remove($w)
            $taskId = $w.Task.id
            Write-Log "[PARALLEL] $taskId 완료 → 검증 시작"

            $out    = Await-AIJob -Ji $w.Ji -Spinner $false
            $result = Get-Section $out "===RESULT_START===" "===RESULT_END==="
            $rf     = Join-Path $script:RESULTS_DIR "${taskId}_result.md"
            Write-File $rf @"
# 결과: $taskId

## 제목
$($w.Task.title)

## 담당 에이전트
$($w.Task.agent)

## 실행 시각
$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

## 출력
$out

## 추출된 결과 요약
$result
"@

            # UNIT_VERIFY — 동기 실행. 그 사이 다른 job들은 백그라운드에서 계속 진행.
            $verifyPrompt = Build-VerifyPrompt-Parallel -task $w.Task -resultOut $out
            $verifyOut    = Invoke-AI -Agent "claude" -Prompt $verifyPrompt -LogTag "${taskId}_verify"
            $vf = Join-Path $script:REVIEWS_DIR "${taskId}_verify.md"
            Write-File $vf $verifyOut

            $verdict = if ($verifyOut -match "(?m)^\s*PASS") { "PASS" } else { "FAIL" }
            if ($verdict -eq "PASS") {
                Set-TaskStatus $taskId "done"
                Write-Log "[PARALLEL] $taskId → DONE ✓"
            } else {
                $q2 = Read-Json $script:QUEUE_FILE
                $t2 = $q2.tasks | Where-Object { $_.id -eq $taskId } | Select-Object -First 1
                $rc = if ($t2 -and $t2.PSObject.Properties["retry_count"]) { [int]$t2.retry_count } else { 0 }
                if ($rc -lt $maxRet) {
                    Set-TaskStatus $taskId "pending" -retryInc 1
                    Write-Log "[PARALLEL] $taskId → RETRY ($($rc+1)/$maxRet)"
                } else {
                    Set-TaskStatus $taskId "failed"
                    Write-Log "[PARALLEL] $taskId → FAILED (재시도 초과)" -Level "WARN"
                }
            }
        }

        # ── 2. 타임아웃 워커 처리 ─────────────────────────────
        $timedOutWorkers = [System.Collections.ArrayList]::new()
        foreach ($w in $workers) {
            if (((Get-Date) - $w.Ji.StartTime).TotalSeconds -ge $script:TIMEOUT_SEC) {
                [void]$timedOutWorkers.Add($w)
            }
        }
        foreach ($w in $timedOutWorkers) {
            Write-Log "[PARALLEL] $($w.Task.id) 타임아웃 → FAILED" -Level "WARN"
            Stop-Job  $w.Ji.Job -ErrorAction SilentlyContinue
            Remove-Job $w.Ji.Job -ErrorAction SilentlyContinue
            if ($w.Ji.GeminiIsoDir -and (Test-Path $w.Ji.GeminiIsoDir)) {
                Remove-Item $w.Ji.GeminiIsoDir -Recurse -Force -ErrorAction SilentlyContinue
            }
            Set-TaskStatus $w.Task.id "failed"
            [void]$workers.Remove($w)
        }

        # ── 3. 새 작업 시작 ──────────────────────────────────
        $readyTasks = @(Get-ReadyTasksList)
        $slots      = $maxWorkers - $workers.Count
        if ($slots -gt 0 -and $readyTasks.Count -gt 0) {
            $toStart = $readyTasks | Select-Object -First $slots
            foreach ($task in $toStart) {
                $tf     = Build-TaskInstructionFile -task $task
                $prompt = Build-ExecutePrompt-Parallel -task $task -taskFilePath $tf
                Write-Log "[PARALLEL] 시작: $($task.id) [$($task.agent)]"
                $ji = Start-AIJob -Agent $task.agent -Prompt $prompt -LogTag $task.id
                Set-TaskStatus $task.id "in_progress"
                [void]$workers.Add(@{ Task=$task; Ji=$ji })
            }
        }

        # ── 4. 진행 상황 ─────────────────────────────────────
        $q         = Read-Json $script:QUEUE_FILE
        $doneCount = @($q.tasks | Where-Object { $_.status -eq "done" }).Count
        $total     = $q.tasks.Count
        $runInfo   = if ($workers.Count -gt 0) {
            ($workers | ForEach-Object { "$($_.Task.id)[$($_.Task.agent)]" }) -join "  "
        } else { "-" }
        Write-Log "[PARALLEL] 실행 중: $($workers.Count)개 [$runInfo]  완료: $doneCount/$total"

        # ── 5. 종료 조건 ─────────────────────────────────────
        $remaining = @($q.tasks | Where-Object { $_.status -notin @("done","failed") }).Count
        if ($remaining -eq 0 -and $workers.Count -eq 0) {
            $failCount = @($q.tasks | Where-Object { $_.status -eq "failed" }).Count
            Write-Log "[PARALLEL] 전체 완료 — 성공: $doneCount  실패: $failCount → INTEGRATE"
            Update-State @{ status="INTEGRATE"; tasks_since_integrate=0 }
            return
        }

        # ── 6. 반복 카운터 ───────────────────────────────────
        $st2 = Read-Json $script:STATE_FILE
        Update-State @{ iteration=($st2.iteration + 1) }
        Write-Log "━━ 반복: $($st2.iteration+1)/$($st2.max_iterations) ━━"
        if (($st2.iteration + 1) -ge $st2.max_iterations) {
            Stop-Fail "[PARALLEL] 최대 반복 $($st2.max_iterations)회 초과"
        }

        Start-Sleep -Seconds 2
    }
}

# ════════════════════════════════════════════════════════════
# 상태별 처리 함수
# ════════════════════════════════════════════════════════════

# INTAKE 오염 감지: 목표에 없는 외부 프로젝트 참조가 있으면 $true
function Test-IntakeContaminated {
    param([string]$intakeText, [string]$goalText)
    # 외부 파일 경로 패턴 (예: path/to/file.py, C:\..., /home/... 등)
    $filePathPattern = '(?:[\w\-]+/){2,}[\w\-]+\.\w+|[A-Za-z]:\\[^\s]+'
    # $fileMatches 로 명명 — PS 자동 변수 $Matches 와 이름 충돌 방지
    $fileMatches = [regex]::Matches($intakeText, $filePathPattern)
    foreach ($m in $fileMatches) {
        # 목표 텍스트에 없는 경로가 INTAKE에 등장하면 오염으로 판단
        if ($goalText -notmatch [regex]::Escape($m.Value)) {
            return $true
        }
    }
    return $false
}

# ── ① INTAKE ─────────────────────────────────────────────
function Run-Intake {
    Write-Log "━━ INTAKE: 프로젝트 유형 분석 ━━"
    $goal = Read-File $script:GOAL_FILE

    $prompt = @"
너는 AI 프로젝트 관리 시스템의 총괄 관리자다.
아래 [사용자 요청] 텍스트만 분석하라. 다른 정보는 없다.

[절대 금지]
- 파일 읽기, 디렉토리 탐색, grep, 웹 검색 등 외부 정보 조회 일체 금지
- 이 프롬프트 텍스트 외의 어떤 소스도 참조하지 마라
- 존재하지 않는 파일이나 프로젝트를 가정하지 마라

[사용자 요청]
$goal

[출력 형식 — 반드시 아래 구분자 사이에만 내용을 작성]

===INTAKE_START===
# 프로젝트 분석

## 프로젝트 유형
(software_development / research_analysis / data_processing / document_creation / mixed 중 하나)

## 핵심 목표
(사용자 요청 텍스트 기반으로 한 문장)

## 필요한 것들
- (요청 텍스트에서 도출 가능한 기술/도구)

## 불명확한 점
- (요청에서 명시되지 않은 사항)

## 예상 복잡도
(simple / medium / complex)
===INTAKE_END===

===PROJECT_TYPE===
(software_development / research_analysis / data_processing / document_creation / mixed)
===PROJECT_TYPE_END===
"@

    $maxRetry = 2
    $attempt  = 0
    $intake   = $null
    $ptype    = ""

    while ($attempt -le $maxRetry) {
        $attempt++
        $out = Invoke-AI -Agent "gemini" -Prompt $prompt -LogTag "intake"

        $intake   = Get-Section $out "===INTAKE_START===" "===INTAKE_END==="
        $ptypeRaw = Get-Section $out "===PROJECT_TYPE===" "===PROJECT_TYPE_END==="
        $ptype    = if ($ptypeRaw) { $ptypeRaw.Trim() } else { "" }
        $intakeText = if ($intake) { $intake } else { $out }

        # 오염 감지: 목표에 없는 파일 경로가 나타나면 재시도
        if (Test-IntakeContaminated $intakeText $goal) {
            Write-Log "INTAKE 오염 감지 (시도 $attempt/$maxRetry): 목표와 무관한 파일 경로 포함 → 재시도" -Level "WARN"
            if ($attempt -le $maxRetry) { continue }
            Write-Log "INTAKE 재시도 초과 — 오염된 분석이지만 진행" -Level "WARN"
        }
        break
    }

    $intakeOut = if ($intake) { $intake } else { $out }
    Write-File $script:INTAKE_FILE $intakeOut
    Write-Log "INTAKE 분석 완료: 유형 = $ptype"
    $ptypeVal = if ($ptype) { $ptype } else { "mixed" }
    Update-State @{ status="CLARIFY"; project_type=$ptypeVal }
}

# ── ①-2 CLARIFY ──────────────────────────────────────────
function Run-Clarify {
    Write-Log "━━ CLARIFY: 요구사항 구체화 질문 ━━"
    $goal   = Read-File $script:GOAL_FILE
    $intake = Read-File $script:INTAKE_FILE

    $prompt = @"
너는 Gemini 총괄 관리자다.
사용자의 요청을 분석했다. 이제 프로젝트를 정확하게 만들기 위해 불명확한 부분을 사용자에게 질문해야 한다.

사용자 요청:
$goal

분석 결과:
$intake

규칙:
- 디자인, UI/UX, 기능 범위, 기술 선택, 우선순위 등 결과물의 방향을 결정하는 중요한 항목만 질문한다.
- 사용자가 명시적으로 언급하지 않은 핵심 결정 사항에 집중한다.
- 질문은 5개 이하로 명확하고 구체적으로 작성한다.
- 각 질문에는 선택 가능한 기본 옵션도 제시한다.

===QUESTIONS_START===
# 구체화가 필요한 사항

1. (질문 내용)
   선택지: A) ... B) ... C) 직접 지정

2. (질문 내용)
   선택지: A) ... B) ... C) 직접 지정

(계속...)
===QUESTIONS_END===
"@

    $out = Invoke-AI -Agent "gemini" -Prompt $prompt -LogTag "clarify"
    $questions = Get-Section $out "===QUESTIONS_START===" "===QUESTIONS_END==="
    $qText = if ($questions) { $questions } else { $out }

    if ($script:GUI) {
        # ── GUI 모드: 파일로 질문을 내보내고 답변 파일을 폴링 ──
        Write-File $script:CLARIFY_QUEST_FILE $qText
        Write-Log "CLARIFY: GUI에서 답변을 기다리는 중... (CLARIFY_QUESTIONS.md 생성)"

        $maxWait = 600  # 최대 10분 대기
        $waited  = 0
        while (-not (Test-Path $script:CLARIFY_FILE) -and $waited -lt $maxWait) {
            Start-Sleep -Seconds 2
            $waited += 2
        }

        Remove-Item $script:CLARIFY_QUEST_FILE -Force -ErrorAction SilentlyContinue

        if (-not (Test-Path $script:CLARIFY_FILE)) {
            Write-Log "CLARIFY: 답변 없음(타임아웃). 기본 추정으로 진행." -Level "WARN"
            Write-File $script:CLARIFY_FILE "(사용자 답변 없음 — AI가 최선 추정으로 진행)"
        } else {
            Write-Log "CLARIFY: 답변 수신 완료"
        }
    } else {
        # ── 콘솔 모드: Read-Host 대화형 입력 ──
        Write-Host ""
        Write-Host "============================================================" -ForegroundColor Cyan
        Write-Host "  Gemini가 다음 사항을 확인하고 싶어합니다" -ForegroundColor Cyan
        Write-Host "============================================================" -ForegroundColor Cyan
        Write-Host $qText -ForegroundColor White
        Write-Host "------------------------------------------------------------" -ForegroundColor Yellow
        Write-Host "  위 질문에 답변해주세요." -ForegroundColor Yellow
        Write-Host "  각 번호에 맞게 자유롭게 작성하고, 완료 후 빈 줄에서 Enter." -ForegroundColor Yellow
        Write-Host "  (건너뛸 항목은 'skip' 입력)" -ForegroundColor Yellow
        Write-Host "------------------------------------------------------------" -ForegroundColor Yellow
        Write-Host ""

        $lines = @()
        while ($true) {
            $line = Read-Host
            if ($line -eq "") { break }
            $lines += $line
        }
        $userAnswers = $lines -join "`n"
        Write-File $script:CLARIFY_FILE "# 요구사항 구체화`n`n## Gemini 질문`n$qText`n`n## 사용자 답변`n$userAnswers"

        Write-Host ""
        Write-Host "  답변 저장됨. 자동 진행합니다." -ForegroundColor Green
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host ""
    }

    Write-Log "CLARIFY 완료 → RESEARCH"
    Update-State @{ status="RESEARCH" }
}

# ── ⑪ REVISE ──────────────────────────────────────────────
function Run-Revise {
    Write-Log "━━ REVISE: 수정 지시 처리 ━━"
    $goal      = Read-File $script:GOAL_FILE
    $criteria  = Read-File $script:CRITERIA_FILE
    $clarify   = Read-File $script:CLARIFY_FILE
    $revisions = Read-File $script:REVISE_FILE
    $intReport = Read-File $script:INTEG_REPORT

    $wsFiles = @(Get-ChildItem $script:WORKSPACE -Recurse -File -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName)
    $fileList = $wsFiles -join "`n"

    $prompt = @"
너는 Gemini 총괄 관리자다.
사용자가 완성된 프로젝트에 대해 수정 요청을 했다.
수정 작업들을 만들어서 Claude와 Gemini 워커에게 배분하라.

원래 목표:
$goal

원래 요구사항 구체화:
$clarify

완료 기준:
$criteria

현재 workspace 파일 목록:
$fileList

이전 통합 검증 보고서:
$intReport

사용자 수정 지시:
$revisions

규칙:
- 수정 지시에 정확히 맞는 작업만 만든다. 불필요한 추가 기능 금지.
- 코딩·파일수정 → agent: "claude"
- 분석·설계검토 → agent: "gemini"
- instruction에 현재 파일 경로와 구체적 수정 내용을 명시한다.

===REVISE_PLAN_START===
# 수정 계획
(수정 방향 설명)
===REVISE_PLAN_END===

===QUEUE_START===
{
  "tasks": [
    {
      "id": "TASK-R01",
      "title": "수정 작업 제목",
      "agent": "claude",
      "status": "pending",
      "retry_count": 0,
      "depends_on": [],
      "instruction": "구체적 수정 지시 (파일 경로 포함)"
    }
  ]
}
===QUEUE_END===
"@

    $out = Invoke-AI -Agent "gemini" -Prompt $prompt -LogTag "revise"

    $revisePlan = Get-Section $out "===REVISE_PLAN_START===" "===REVISE_PLAN_END==="
    $queueRaw   = Get-Section $out "===QUEUE_START===" "===QUEUE_END==="

    $revisePlanFile = Join-Path $script:ROOT "REVISE_PLAN.md"
    $planOut = if ($revisePlan) { $revisePlan } else { $out }
    Write-File $revisePlanFile $planOut

    if ($queueRaw) {
        try {
            $q = Normalize-Queue ($queueRaw.Trim() | ConvertFrom-Json)
            Write-Json $script:QUEUE_FILE $q
            Write-Log "REVISE: 수정 작업 $($q.tasks.Count)개 등록"
        } catch {
            Write-Log "REVISE 큐 파싱 실패 → 단일 수정 작업 생성" -Level "WARN"
            $q = [PSCustomObject]@{ tasks = @([PSCustomObject]@{
                id="TASK-R01"; title="전체 수정"; agent="claude"; status="pending"
                retry_count=0; depends_on=$null
                instruction="REVISIONS.md의 수정 지시에 따라 workspace/ 파일들을 수정한다."
                is_integration_task=$false
            })}
            Write-Json $script:QUEUE_FILE $q
        }
    }

    Update-State @{ status="PARALLEL_EXECUTE"; is_complete=$false; tasks_since_integrate=0 }
    Write-Log "REVISE 완료 → PARALLEL_EXECUTE"
}

# ── ② RESEARCH ────────────────────────────────────────────
function Run-Research {
    Write-Log "━━ RESEARCH: 요구사항 조사 ━━"
    $goal    = Read-File $script:GOAL_FILE
    $intake  = Read-File $script:INTAKE_FILE
    $clarify = Read-File $script:CLARIFY_FILE

    $prompt = @"
너는 AI 프로젝트 관리자다. 프로젝트를 성공시키기 위해 리서치를 수행하라.

원래 목표:
$goal

프로젝트 분석:
$intake

사용자 요구사항 구체화 (반드시 이 내용을 기준으로 삼을 것):
$clarify

아래를 조사하고 정리하라:
1. 이 프로젝트에 가장 적합한 기술 스택 / 접근법 (이유 포함)
2. 유사 사례나 참고할 패턴
3. 예상되는 기술적 어려움과 해결 방법
4. 반드시 지켜야 할 제약 조건
5. Claude(코드/실행 담당)에게 줄 핵심 지침

===RESEARCH_START===
# 리서치 결과

## 권장 기술 스택 / 접근법
(구체적으로)

## 참고 패턴
(유사 사례)

## 예상 어려움과 대응
| 어려움 | 대응 방법 |
|--------|-----------|

## 핵심 제약 조건
- (반드시 지킬 것들)

## Claude 실행 지침
- (Claude가 작업할 때 꼭 알아야 할 것들)
===RESEARCH_END===
"@

    $out = Invoke-AI -Agent "gemini" -Prompt $prompt -LogTag "research"
    $research = Get-Section $out "===RESEARCH_START===" "===RESEARCH_END==="
    $researchOut = if ($research) { $research } else { $out }
    Write-File $script:RESEARCH_FILE $researchOut
    Write-Log "RESEARCH 완료"
    Update-State @{ status="DEEP_RESEARCH" }
}

# ── ③ DEEP_RESEARCH ─────────────────────────────────────────
function Run-DeepResearch {
    Write-Log "━━ DEEP_RESEARCH: 웹 딥서치 수행 ━━"
    $goal     = Read-File $script:GOAL_FILE
    $research = Read-File $script:RESEARCH_FILE

    $prompt = @"
너는 AI 프로젝트 리서처다. 아래 목표와 초기 리서치를 바탕으로
실제 인터넷을 검색하여 심층 리서치를 수행하라.

목표:
$goal

초기 리서치:
$research

지시:
1. 관련 최신 기술·라이브러리·패키지 버전을 검색하라.
2. 유사 오픈소스 프로젝트나 레퍼런스 구현을 찾아라.
3. 알려진 버그·제한사항·주의사항을 검색하라.
4. 실제 사용 사례나 튜토리얼을 찾아라.

===DEEP_RESEARCH_START===
# 딥리서치 결과

## 최신 기술 현황
(검색으로 확인한 최신 버전·동향)

## 참고 구현 및 레퍼런스
(실제 찾은 링크·코드·패턴)

## 주의사항 및 알려진 이슈
(버그·제한·호환성 문제)

## 실행 권고사항
(위 검색을 바탕으로 프로젝트에 직접 적용할 권고)
===DEEP_RESEARCH_END===
"@

    $out  = Invoke-AI -Agent "gemini" -Prompt $prompt -LogTag "deep_research" -AllowTools
    $deep = Get-Section $out "===DEEP_RESEARCH_START===" "===DEEP_RESEARCH_END==="
    Write-File $script:DEEP_RESEARCH_FILE (if ($deep) { $deep } else { $out })
    Write-Log "DEEP_RESEARCH 완료"
    Update-State @{ status="HALLCHECK" }
}

# ── ④ HALLCHECK ──────────────────────────────────────────────
function Run-HallCheck {
    Write-Log "━━ HALLCHECK: 딥리서치 환각 검증 ━━"
    $goal    = Read-File $script:GOAL_FILE
    $deepRes = Read-File $script:DEEP_RESEARCH_FILE

    $prompt = @"
너는 코드 품질 및 정보 검증 전문가다. 아래 딥리서치 결과를 비판적으로 검토하여
환각(hallucination)이나 사실 오류가 없는지 확인하라.

프로젝트 목표: $goal

딥리서치 결과:
$deepRes

검증 항목:
1. 언급된 라이브러리/패키지가 실제로 존재하는가?
2. 버전 번호가 현실적인가?
3. 제시된 API나 함수 시그니처가 일반적으로 올바른가?
4. 근거 없는 주장이나 추측이 섞여 있는가?

===HALLCHECK_START===
# 환각 검증 보고서

## 검증 결과: PASS / PARTIAL / FAIL
(PASS: 신뢰도 높음 / PARTIAL: 일부 주의 필요 / FAIL: 심각한 오류 발견)

## 확인된 사항
- (사실로 확인된 항목들)

## 의심 항목
- (검증 불가 또는 의심스러운 항목들)

## 수정 권고
- (잘못된 정보를 올바르게 수정한 내용)
===HALLCHECK_END===
"@

    $out   = Invoke-AI -Agent "codex" -Prompt $prompt -LogTag "hallcheck"
    $check = Get-Section $out "===HALLCHECK_START===" "===HALLCHECK_END==="
    Write-File $script:HALLCHECK_FILE (if ($check) { $check } else { $out })
    Write-Log "HALLCHECK 완료"
    Update-State @{ status="PLAN" }
}

# ── ③ PLAN ────────────────────────────────────────────────
function Run-Plan {
    Write-Log "━━ PLAN: 작업 계획 수립 ━━"
    $goal        = Read-File $script:GOAL_FILE
    $intake      = Read-File $script:INTAKE_FILE
    $clarify     = Read-File $script:CLARIFY_FILE
    $research    = Read-File $script:RESEARCH_FILE
    $deepRes     = Read-File $script:DEEP_RESEARCH_FILE
    $hallCheck   = Read-File $script:HALLCHECK_FILE

    $prompt = @"
너는 AI 프로젝트 관리자다. 아래 정보를 바탕으로 구체적인 실행 계획을 만들어라.

목표: $goal

분석: $intake

사용자 요구사항 구체화 (이 내용이 최우선 기준이다. 반드시 반영할 것):
$clarify

리서치: $research

딥리서치 (최신 외부 정보 — 이 내용을 기술 선택에 반드시 반영할 것):
$deepRes

환각 검증 보고서 (FAIL/PARTIAL 항목은 계획에서 제외하거나 수정할 것):
$hallCheck

역할:
- Gemini 총괄(너): 계획, 판단, 검토, 필요 시 Gemini 워커 소환
- Gemini 워커: 분석, 설계, 문서화, 리서치 서브태스크 (agent="gemini")
- Claude: 코드 작성, 파일 생성, 구현, 통합 테스트 (agent="claude")
- Codex: 코드 품질·보안·버그 검토 (시스템이 자동 호출, 별도 지정 불필요)

규칙:
- 코딩·파일생성이 필요한 작업 → agent: "claude"
- 분석·설계·문서·리서치 서브태스크 → agent: "gemini" (Gemini 워커 소환)
- 작업은 검토 가능한 작은 단위로 나눈다. (한 번에 하나의 파일이나 기능)
- 각 작업에 depends_on으로 선행 작업을 명시한다.
- 중간 통합 체크포인트를 계획에 포함한다.
- instruction 필드에 담당 AI에게 줄 구체적 지시를 작성한다.

===PLAN_START===
# 전체 계획
(계획 설명)
===PLAN_END===

===CRITERIA_START===
# 완료 판정 기준
- (구체적이고 검증 가능한 기준들)
===CRITERIA_END===

===QUEUE_START===
{
  "tasks": [
    {
      "id": "TASK-001",
      "title": "작업 제목",
      "agent": "claude",
      "status": "pending",
      "retry_count": 0,
      "depends_on": [],
      "instruction": "Claude에게 줄 구체적인 실행 지시"
    }
  ]
}
===QUEUE_END===
"@

    $out = Invoke-AI -Agent "gemini" -Prompt $prompt -LogTag "plan"

    $plan     = Get-Section $out "===PLAN_START===" "===PLAN_END==="
    $criteria = Get-Section $out "===CRITERIA_START===" "===CRITERIA_END==="
    $queueRaw = Get-Section $out "===QUEUE_START===" "===QUEUE_END==="

    $planOut = if ($plan) { $plan } else { $out }
    Write-File $script:PLAN_FILE $planOut
    if ($criteria) { Write-File $script:CRITERIA_FILE $criteria }

    if ($queueRaw) {
        try {
            $q = Normalize-Queue ($queueRaw.Trim() | ConvertFrom-Json)
            Write-Json $script:QUEUE_FILE $q
            Write-Log "PLAN: TASK_QUEUE.json 저장 ($($q.tasks.Count)개 작업)"
        } catch {
            $el = Join-Path $script:LOGS_DIR "json_err_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
            Write-File $el $queueRaw
            Write-Log "TASK_QUEUE JSON 파싱 실패 → 기본 큐 사용 ($el)" -Level "WARN"
            $q = [PSCustomObject]@{ tasks = @([PSCustomObject]@{
                id="TASK-001"; title="전체 구현"; agent="claude"; status="pending"
                retry_count=0; depends_on=$null; instruction="GOAL.md와 RESEARCH.md를 참고해 전체를 구현한다."
                is_integration_task=$false
            })}
            Write-Json $script:QUEUE_FILE $q
        }
    }

    # 작업 수 기반 max_iterations 동적 계산
    $taskCount  = if ($null -ne $q -and $q.tasks) { $q.tasks.Count } else { 1 }
    $dynMaxIter = [Math]::Max($taskCount * 5, 50)
    Update-State @{ status="PARALLEL_EXECUTE"; max_iterations=$dynMaxIter }
    Write-Log "PLAN 완료: 작업 ${taskCount}개 → max_iterations 동적 설정 $dynMaxIter → PARALLEL_EXECUTE"
}

# ── ④ DISPATCH ────────────────────────────────────────────
function Run-Dispatch {
    $next = Get-NextTask
    if (-not $next) {
        $q = Read-Json $script:QUEUE_FILE
        $pending = @($q.tasks | Where-Object { $_.status -eq "pending" }).Count
        if ($pending -eq 0) {
            Write-Log "DISPATCH: 모든 작업 완료 → INTEGRATE"
            Update-State @{ status="INTEGRATE" }
        } else {
            Stop-Fail "실행 가능한 작업 없음 (의존성 미해결, pending=$pending)"
        }
        return
    }

    $st = Read-Json $script:STATE_FILE
    if ($next.retry_count -ge $st.max_retries_per_task) {
        Set-TaskStatus $next.id "failed"
        Stop-Fail "작업 $($next.id) 최대 재시도 초과"
    }

    # 작업 지시서 생성
    $tf = Join-Path $script:TASKS_DIR "$($next.id).md"
    $goal     = Read-File $script:GOAL_FILE
    $research = Read-File $script:RESEARCH_FILE
    $criteria = Read-File $script:CRITERIA_FILE

    Write-File $tf @"
# 작업 지시서: $($next.id)

## 제목
$($next.title)

## 지시 내용
$($next.instruction)

## workspace 경로
$script:WORKSPACE

## 전체 목표
$goal

## 리서치 결과 (기술 제약 등)
$research

## 완료 기준
$criteria

## 주의
- 파일 생성·수정은 반드시 위 workspace 경로($script:WORKSPACE) 내에서만 한다.
- 상대 경로 금지. 절대 경로를 사용한다.
- 작업 완료 후 변경 파일 목록, 실행 방법, 자체 검증 결과를 요약한다.
- 보안 취약점을 만들지 않는다.
"@

    Set-TaskStatus $next.id "running"
    Update-State @{ status="EXECUTE"; current_task_id=$next.id }
    Write-Log "DISPATCH: $($next.id) 배정 완료"
}

# ── ⑤ EXECUTE ─────────────────────────────────────────────
function Run-Execute {
    $st     = Read-Json $script:STATE_FILE
    $taskId = $st.current_task_id
    $q      = Read-Json $script:QUEUE_FILE
    $task   = $q.tasks | Where-Object { $_.id -eq $taskId } | Select-Object -First 1
    if (-not $task) { Stop-Fail "EXECUTE: 작업 없음 $taskId" }

    $tf      = Join-Path $script:TASKS_DIR "$taskId.md"
    $taskTxt = Read-File $tf

    $execAgent = $task.agent
    $agentRole = switch ($execAgent) {
        "gemini" { "Gemini 워커이며 분석·설계·문서화를 담당한다." }
        "codex"  { "Codex이며 코드 구현을 담당한다." }
        default  { "Claude이며 코드 작성·파일 생성·구현을 담당한다." }
    }

    $prompt = @"
너는 $agentRole

작업 지시서:
$taskTxt

수행 지침:
- 파일 생성·수정 경로: $script:WORKSPACE
- 반드시 위 경로 내에서만 파일을 만든다. 상대 경로가 아닌 절대 경로를 사용한다.
- 실제로 동작하는 완성본을 만든다.
- 작업 완료 후 반드시 아래 형식으로 요약한다:

===RESULT_START===
## 완료된 작업
(무엇을 했는지)

## 생성/수정한 파일
- (파일 경로 목록)

## 실행 방법
(어떻게 실행하는지)

## 자체 검증
(내가 확인한 것들, 예상되는 문제)
===RESULT_END===
"@

    $out = Invoke-AI -Agent $execAgent -Prompt $prompt -LogTag $taskId

    $result = Get-Section $out "===RESULT_START===" "===RESULT_END==="
    $rf = Join-Path $script:RESULTS_DIR "${taskId}_result.md"
    Write-File $rf @"
# 결과: $taskId

## 제목
$($task.title)

## 담당 에이전트
$execAgent

## 실행 시각
$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

## 출력
$out

## 추출된 결과 요약
$result
"@

    Update-State @{ status="UNIT_VERIFY"; last_agent=$execAgent; last_result_file=$rf }
    Write-Log "EXECUTE 완료 ($execAgent): $rf"
}

# ── ⑥ UNIT_VERIFY ─────────────────────────────────────────
function Run-UnitVerify {
    $st     = Read-Json $script:STATE_FILE
    $taskId = $st.current_task_id
    $rf     = $st.last_result_file

    $q    = Read-Json $script:QUEUE_FILE
    $task = $q.tasks | Where-Object { $_.id -eq $taskId } | Select-Object -First 1

    $taskTxt   = Read-File (Join-Path $script:TASKS_DIR "$taskId.md")
    $resultTxt = Read-File $rf
    $criteria  = Read-File $script:CRITERIA_FILE

    $prompt = @"
너는 Claude이며 방금 네가 수행한 작업의 결과를 스스로 검증한다.

작업 지시서:
$taskTxt

작업 결과:
$resultTxt

전체 완료 기준:
$criteria

검증 항목:
1. 작업 지시서의 요구사항을 모두 수행했는가?
2. 생성한 코드/파일이 실제로 동작할 것인가?
3. 보안 취약점이나 명백한 버그가 있는가?
4. 다음 작업 또는 통합 시 문제가 될 수 있는 것이 있는가?

===VERIFY_START===
## Verdict
PASS 또는 FAIL

## 확인된 문제
- (없으면 "없음")

## 수정 필요 사항
- (FAIL인 경우 구체적으로)

## 다음 작업을 위한 인수인계
- (다음 작업자가 알아야 할 것)
===VERIFY_END===
"@

    $out = Invoke-AI -Agent "claude" -Prompt $prompt -LogTag "${taskId}_verify"

    $vf = Join-Path $script:REVIEWS_DIR "${taskId}_verify.md"
    Write-File $vf $out
    Update-State @{ status="DECIDE"; last_review_file=$vf }
    Write-Log "UNIT_VERIFY 완료: $vf"
}

# ── ⑦ DECIDE ──────────────────────────────────────────────
function Run-Decide {
    $st     = Read-Json $script:STATE_FILE
    $taskId = $st.current_task_id
    $rf     = $st.last_result_file
    $vf     = $st.last_review_file

    $q    = Read-Json $script:QUEUE_FILE
    $task = $q.tasks | Where-Object { $_.id -eq $taskId } | Select-Object -First 1

    $goal      = Read-File $script:GOAL_FILE
    $criteria  = Read-File $script:CRITERIA_FILE
    $taskTxt   = Read-File (Join-Path $script:TASKS_DIR "$taskId.md")
    $resultTxt = Read-File $rf
    $verifyTxt = Read-File $vf
    $queueTxt  = Read-File $script:QUEUE_FILE
    $stateTxt  = Read-File $script:STATE_FILE

    $allDone = (@($q.tasks | Where-Object { $_.status -eq "pending" }).Count -eq 0)

    $prompt = @"
너는 Gemini이며 프로젝트 총괄 관리자다.
현재 작업 결과와 검증 결과를 보고 다음 행동을 결정하라.

목표: $goal
완료 기준: $criteria

현재 작업 ($taskId): $($task.title)
작업 결과 요약:
$resultTxt

자체 검증 결과:
$verifyTxt

전체 작업 큐:
$queueTxt

현재 상태:
$stateTxt

남은 pending 작업 수: $(@($q.tasks | Where-Object { $_.status -eq "pending"}).Count)

판단 기준:
- 자체 검증이 PASS이고 남은 작업이 있으면 → CONTINUE
- 자체 검증이 FAIL이면 → RETRY (수정 지시 포함)
- 코드가 여러 개 완성되어 통합 테스트가 필요하면 → INTEGRATE_NOW
- 모든 완료 기준이 충족되면 → FINISH
- 복구 불가능한 문제가 있으면 → FAILED
- 새로운 작업이 필요하면 → ADD_TASK

반드시 아래 JSON만 출력하라. 다른 텍스트 없이.

{
  "decision": "CONTINUE",
  "reason": "결정 이유",
  "next_task_id": null,
  "fix_instruction": "",
  "new_task": null,
  "is_complete": false
}

decision: CONTINUE / RETRY / ADD_TASK / INTEGRATE_NOW / FINISH / FAILED
new_task 예시 (ADD_TASK일 때):
  { "title": "작업명", "instruction": "구체적 지시", "depends_on": ["$taskId"] }
"@

    $out = Invoke-AI -Agent "gemini" -Prompt $prompt -LogTag "${taskId}_decide"

    # JSON 추출
    $decision = $null
    try {
        if ($out -match '(?s)\{.*"decision".*\}') {
            $decision = $Matches[0] | ConvertFrom-Json
        } else { $decision = $out.Trim() | ConvertFrom-Json }
    } catch {
        $el = Join-Path $script:LOGS_DIR "json_err_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
        Write-File $el $out
        Write-Log "DECIDE JSON 파싱 실패 → CONTINUE 기본값 ($el)" -Level "WARN"
        $decision = [PSCustomObject]@{ decision="CONTINUE"; reason="파싱실패"; next_task_id=$null; fix_instruction=""; new_task=$null; is_complete=$false }
    }

    Write-Log "DECIDE: $($decision.decision) — $($decision.reason)"

    switch ($decision.decision) {
        "FINISH" {
            Set-TaskStatus $taskId "done"
            Update-State @{ status="FINISH"; is_complete=$true }
        }
        "FAILED" {
            Set-TaskStatus $taskId "failed"
            Stop-Fail "Gemini 실패 판정: $($decision.reason)"
        }
        "CONTINUE" {
            Set-TaskStatus $taskId "done"
            $tasksCount = $st.tasks_since_integrate + 1
            $shouldIntegrate = ($tasksCount -ge $st.integrate_every_n)
            if ($shouldIntegrate) {
                Update-State @{ status="INTEGRATE"; tasks_since_integrate=0 }
            } else {
                Update-State @{ status="DISPATCH"; tasks_since_integrate=$tasksCount }
            }
        }
        "RETRY" {
            Set-TaskStatus $taskId "pending" -retryInc 1
            # 수정 지시 업데이트
            if ($decision.fix_instruction) {
                $q2 = Read-Json $script:QUEUE_FILE
                foreach ($t in $q2.tasks) {
                    if ($t.id -eq $taskId) { $t.instruction = $decision.fix_instruction; break }
                }
                Write-Json $script:QUEUE_FILE $q2
            }
            Update-State @{ status="DISPATCH" }
        }
        "ADD_TASK" {
            Set-TaskStatus $taskId "done"
            if ($decision.new_task) {
                $nid = Get-NewTaskId
                $deps = if ($decision.new_task.PSObject.Properties["depends_on"]) {
                            @($decision.new_task.depends_on)
                        } else { @($taskId) }
                Add-Task $nid $decision.new_task.title "claude" $decision.new_task.instruction $deps
            }
            Update-State @{ status="DISPATCH"; tasks_since_integrate=($st.tasks_since_integrate+1) }
        }
        "INTEGRATE_NOW" {
            Set-TaskStatus $taskId "done"
            Update-State @{ status="INTEGRATE"; tasks_since_integrate=0 }
        }
        default {
            Set-TaskStatus $taskId "done"
            Update-State @{ status="DISPATCH" }
        }
    }
}

# ── ⑧ INTEGRATE ───────────────────────────────────────────
function Run-Integrate {
    Write-Log "━━ INTEGRATE: 통합 테스트 ━━"
    $goal     = Read-File $script:GOAL_FILE
    $criteria = Read-File $script:CRITERIA_FILE
    $research = Read-File $script:RESEARCH_FILE

    # workspace 파일 목록 수집 (@() 로 감싸서 $null.Count 방지)
    $wsFiles = @(Get-ChildItem $script:WORKSPACE -Recurse -File -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName)
    $fileList = $wsFiles -join "`n"
    $fileCount = $wsFiles.Count

    # 완료된 작업 요약
    $doneResults = Get-ChildItem $script:RESULTS_DIR -Filter "*_result.md" |
        ForEach-Object { "### $($_.Name)`n$(Get-Content $_.FullName -Raw -Encoding UTF8)" } |
        Out-String

    $prompt = @"
너는 Claude이며 지금까지 만들어진 모든 결과물을 통합 검증한다.

프로젝트 목표:
$goal

완료 기준:
$criteria

기술 제약 (리서치 결과):
$research

workspace 파일 목록 ($fileCount 개):
$fileList

지금까지 완료된 작업 결과 요약:
$doneResults

수행할 것:
1. 각 파일의 역할과 연결 관계를 파악한다.
2. 파일 간 import/호출/의존성이 올바른지 확인한다.
3. 전체를 실행했을 때 발생할 수 있는 오류를 찾는다.
4. 완료 기준 항목별로 충족 여부를 판단한다.
5. 발견된 오류를 수정하기 위한 구체적인 지시를 작성한다.

===INTEGRATION_START===
# 통합 검증 보고서

## 파일 연결 관계 분석
(각 파일의 역할과 의존성)

## 발견된 오류 / 문제
| 유형 | 파일 | 내용 | 심각도 |
|------|------|------|--------|

## 완료 기준 충족 현황
| 기준 | 충족 여부 | 비고 |
|------|-----------|------|

## 통합 판정
PASS 또는 FAIL

## 수정 필요 작업 목록
(FAIL인 경우 각 문제에 대한 구체적 수정 지시)
- 문제1: [수정 지시]
- 문제2: [수정 지시]

## 남은 작업
(완료 기준을 충족하기 위해 아직 없는 것들)
===INTEGRATION_END===
"@

    $out = Invoke-AI -Agent "claude" -Prompt $prompt -LogTag "integrate"
    $report = Get-Section $out "===INTEGRATION_START===" "===INTEGRATION_END==="
    $reportOut = if ($report) { $report } else { $out }
    Write-File $script:INTEG_REPORT $reportOut
    Write-Log "INTEGRATE 완료: $script:INTEG_REPORT"
    Update-State @{ status="CODEX_REVIEW" }
}

# ── ⑨ INT_REVIEW ─────────────────────────────────────────
# ── ⑧-2 CODEX_REVIEW ─────────────────────────────────────
function Run-CodexReview {
    Write-Log "━━ CODEX_REVIEW: Codex 코드 품질·보안 검토 ━━"
    $goal      = Read-File $script:GOAL_FILE
    $criteria  = Read-File $script:CRITERIA_FILE
    $intReport = Read-File $script:INTEG_REPORT

    $wsFiles = @(Get-ChildItem $script:WORKSPACE -Recurse -File -ErrorAction SilentlyContinue)
    $fileContents = foreach ($f in $wsFiles) {
        $rel = $f.FullName.Replace($script:WORKSPACE, "workspace")
        "### $rel`n" + [System.IO.File]::ReadAllText($f.FullName, [Text.Encoding]::UTF8)
    }
    $allCode = $fileContents -join "`n`n---`n`n"

    $prompt = @"
You are Codex, an expert code reviewer. Review all the code below for quality, bugs, and security issues.

Project goal: $goal
Completion criteria: $criteria

Integration report:
$intReport

Source code to review:
$allCode

Perform a thorough review covering:
1. Bugs and logic errors
2. Security vulnerabilities
3. Code quality and maintainability
4. Missing functionality vs. requirements
5. Performance issues

===CODEX_REVIEW_START===
## Critical Issues (must fix)
| File | Line | Issue | Severity |
|------|------|-------|----------|

## Warnings (should fix)
| File | Issue | Recommendation |
|------|-------|----------------|

## Code Quality Assessment
(overall rating and comments)

## Security Assessment
(any security concerns)

## Verdict
PASS or FAIL

## Fix Instructions
(specific instructions for each critical issue)
===CODEX_REVIEW_END===
"@

    $codexReviewFile = Join-Path $script:INTEG_DIR "CODEX_REVIEW.md"
    $out = Invoke-AI -Agent "codex" -Prompt $prompt -LogTag "codex_review"
    $review = Get-Section $out "===CODEX_REVIEW_START===" "===CODEX_REVIEW_END==="
    $reviewOut = if ($review) { $review } else { $out }
    Write-File $codexReviewFile $reviewOut
    Write-Log "CODEX_REVIEW 완료: $codexReviewFile"
    Update-State @{ status="GEMINI_CHECK"; last_result_file=$codexReviewFile }
}

# ── ⑧-3 GEMINI_CHECK ──────────────────────────────────────
function Run-GeminiCheck {
    Write-Log "━━ GEMINI_CHECK: Gemini의 Codex 검토 결과 검증 ━━"
    $goal         = Read-File $script:GOAL_FILE
    $criteria     = Read-File $script:CRITERIA_FILE
    $intReport    = Read-File $script:INTEG_REPORT
    $codexReview  = Read-File (Join-Path $script:INTEG_DIR "CODEX_REVIEW.md")

    $prompt = @"
너는 Gemini 총괄 관리자다.
Codex가 수행한 코드 검토 결과를 검증하라.

프로젝트 목표: $goal
완료 기준: $criteria

통합 검증 보고서:
$intReport

Codex 검토 결과:
$codexReview

검증 항목:
1. Codex가 제기한 각 이슈가 실제로 유효한가? (오탐 없는가?)
2. Codex가 놓친 중요한 문제가 있는가?
3. Codex의 수정 지시가 올바른 방향인가?
4. 전체적으로 프로젝트 목표와 완료 기준에 비춰 현재 상태는?

반드시 아래 JSON만 출력하라.

{
  "codex_review_valid": true,
  "missed_issues": [],
  "incorrect_suggestions": [],
  "overall_status": "PASS",
  "reason": "판단 근거",
  "additional_fix_tasks": []
}

additional_fix_tasks 예시:
[{ "title": "작업명", "instruction": "구체적 지시", "agent": "claude" }]
"@

    $out = Invoke-AI -Agent "gemini" -Prompt $prompt -LogTag "gemini_check"
    $geminiCheckFile = Join-Path $script:INTEG_DIR "GEMINI_CHECK.md"
    Write-File $geminiCheckFile $out

    $result = $null
    try {
        if ($out -match '(?s)\{.*"overall_status".*\}') {
            $result = $Matches[0] | ConvertFrom-Json
        } else { $result = $out.Trim() | ConvertFrom-Json }
    } catch {
        Write-Log "GEMINI_CHECK JSON 파싱 실패 → CLAUDE_RECHECK 진행" -Level "WARN"
        $result = [PSCustomObject]@{ overall_status="PASS"; additional_fix_tasks=@() }
    }

    Write-Log "GEMINI_CHECK 판정: $($result.overall_status)"

    $extraTasks = @($result.additional_fix_tasks | Where-Object { $_ })
    if ($extraTasks.Count -gt 0) {
        $q = Read-Json $script:QUEUE_FILE
        $maxNum = ($q.tasks | ForEach-Object {
            if ($_.id -match 'TASK-(\d+)') { [int]$Matches[1] } else { 0 }
        } | Measure-Object -Max).Maximum
        foreach ($ft in $extraTasks) {
            $maxNum++
            $nid = "TASK-{0:D3}" -f $maxNum
            $ag = if ($ft.PSObject.Properties["agent"]) { $ft.agent } else { "claude" }
            Add-Task $nid $ft.title $ag $ft.instruction @()
        }
        Write-Log "GEMINI_CHECK: 추가 수정 작업 $($extraTasks.Count)개 등록"
    }

    Update-State @{ status="CLAUDE_RECHECK" }
}

# ── ⑧-4 CLAUDE_RECHECK ────────────────────────────────────
function Run-ClaudeRecheck {
    Write-Log "━━ CLAUDE_RECHECK: Claude의 교차 검토 재검증 ━━"
    $goal        = Read-File $script:GOAL_FILE
    $criteria    = Read-File $script:CRITERIA_FILE
    $intReport   = Read-File $script:INTEG_REPORT
    $codexReview = Read-File (Join-Path $script:INTEG_DIR "CODEX_REVIEW.md")
    $geminiCheck = Read-File (Join-Path $script:INTEG_DIR "GEMINI_CHECK.md")

    $prompt = @"
너는 Claude이며 독립적인 재검토자로서 두 AI의 검토 결과를 교차 검증한다.

프로젝트 목표: $goal
완료 기준: $criteria

통합 검증 보고서:
$intReport

Codex 검토 결과:
$codexReview

Gemini 검증 결과:
$geminiCheck

수행할 것:
1. Codex와 Gemini의 검토가 서로 일치하는가? 모순이 있는가?
2. 두 검토 모두 놓친 사각지대가 있는가?
3. 제안된 수정 지시들이 실제로 구현 가능하고 올바른가?
4. 최종적으로 이 프로젝트는 목표를 달성했는가?

===CLAUDE_RECHECK_START===
## 교차 검토 결과

### Codex vs Gemini 일치/불일치
(상세 비교)

### 두 검토가 놓친 사각지대
(발견된 경우)

### 수정 지시 검증
(각 수정 지시의 타당성)

### 최종 의견
AGREE (두 검토 모두 타당) / PARTIAL (일부 수정 필요) / DISAGREE (재검토 필요)

### 추가 권고사항
(있는 경우)
===CLAUDE_RECHECK_END===
"@

    $out = Invoke-AI -Agent "claude" -Prompt $prompt -LogTag "claude_recheck"
    $recheckFile = Join-Path $script:INTEG_DIR "CLAUDE_RECHECK.md"
    $review = Get-Section $out "===CLAUDE_RECHECK_START===" "===CLAUDE_RECHECK_END==="
    $recheckOut = if ($review) { $review } else { $out }
    Write-File $recheckFile $recheckOut
    Write-Log "CLAUDE_RECHECK 완료: $recheckFile"
    Update-State @{ status="INT_REVIEW" }
}

# ── ⑨ INT_REVIEW ─────────────────────────────────────────
function Run-IntegrationReview {
    Write-Log "━━ INT_REVIEW: 통합 결과 판정 ━━"
    $goal      = Read-File $script:GOAL_FILE
    $criteria  = Read-File $script:CRITERIA_FILE
    $intReport = Read-File $script:INTEG_REPORT
    $queueTxt  = Read-File $script:QUEUE_FILE
    $stateTxt  = Read-File $script:STATE_FILE

    $codexReview  = Read-File (Join-Path $script:INTEG_DIR "CODEX_REVIEW.md")
    $geminiCheck  = Read-File (Join-Path $script:INTEG_DIR "GEMINI_CHECK.md")
    $claudeRecheck = Read-File (Join-Path $script:INTEG_DIR "CLAUDE_RECHECK.md")

    $prompt = @"
너는 Gemini 총괄 관리자다. 세 AI의 교차 검토 결과를 종합하여 최종 판정을 내려라.

목표: $goal
완료 기준: $criteria

통합 검증 보고서 (Claude):
$intReport

코드 품질·보안 검토 (Codex):
$codexReview

Gemini 검증 결과:
$geminiCheck

Claude 교차 재검토:
$claudeRecheck

현재 작업 큐:
$queueTxt

판단 기준:
- 세 검토 모두 PASS이고 완료 기준 충족 → FINISH
- 수정 필요 문제가 있으면 → fix_tasks에 각 수정 작업 지정 (agent: "claude" 또는 "gemini")
- 복구 불가능한 상황 → FAILED

반드시 아래 JSON만 출력하라.

{
  "verdict": "PASS",
  "reason": "판정 이유",
  "is_complete": true,
  "fix_tasks": []
}

fix_tasks 예시:
[
  { "title": "수정 작업 제목", "instruction": "구체적 지시", "agent": "claude", "depends_on": [] }
]
"@

    $out = Invoke-AI -Agent "gemini" -Prompt $prompt -LogTag "int_review"

    $result = $null
    try {
        if ($out -match '(?s)\{.*"verdict".*\}') {
            $result = $Matches[0] | ConvertFrom-Json
        } else { $result = $out.Trim() | ConvertFrom-Json }
    } catch {
        Write-Log "INT_REVIEW JSON 파싱 실패 → FINISH 기본값" -Level "WARN"
        $result = [PSCustomObject]@{ verdict="PASS"; reason="파싱실패"; is_complete=$true; fix_tasks=@() }
    }

    Write-Log "INT_REVIEW 판정: $($result.verdict) — $($result.reason)"

    if ($result.verdict -eq "PASS" -and $result.is_complete) {
        Update-State @{ status="FINISH"; is_complete=$true }
    } elseif (@($result.fix_tasks | Where-Object { $_ }).Count -gt 0) {
        $fixList = @($result.fix_tasks | Where-Object { $_ })
        $q = Read-Json $script:QUEUE_FILE
        $maxNum = ($q.tasks | ForEach-Object {
            if ($_.id -match 'TASK-(\d+)') { [int]$Matches[1] } else { 0 }
        } | Measure-Object -Max).Maximum

        foreach ($ft in $fixList) {
            $maxNum++
            $nid = "TASK-{0:D3}" -f $maxNum
            $deps = if ($ft.PSObject.Properties["depends_on"]) { @($ft.depends_on) } else { @() }
            Add-Task $nid $ft.title "claude" $ft.instruction $deps
        }
        Update-State @{ status="DISPATCH"; tasks_since_integrate=0 }
        Write-Log "INT_REVIEW: 수정 작업 $($fixList.Count)개 추가 → DISPATCH"
    } else {
        Update-State @{ status="DISPATCH" }
    }
}

# ── ⑩ FINISH ─────────────────────────────────────────────
function Run-Finish {
    $q  = Read-Json $script:QUEUE_FILE
    $st = Read-Json $script:STATE_FILE

    $lines = ($q.tasks | ForEach-Object {
        "| $($_.id) | $($_.status) | $($_.agent) | $($_.title.Substring(0,[Math]::Min(50,$_.title.Length))) |"
    }) -join "`n"

    $wsFiles = Get-ChildItem $script:WORKSPACE -Recurse -File -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName
    $fileList = ($wsFiles | ForEach-Object { "- $_" }) -join "`n"

    $summary = @"
# 최종 완료 보고서

## 완료 시각
$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

## 총 반복
$($st.iteration)회

## 작업 목록
| ID | 상태 | 에이전트 | 제목 |
|----|------|----------|------|
$lines

## 생성된 파일
$fileList

## 결과물 위치
- $script:WORKSPACE  — 실제 프로젝트 파일
- results/    — 각 작업 실행 결과
- integration/INTEGRATION_REPORT.md — 통합 검증 보고서
"@

    $sf = Join-Path $script:RESULTS_DIR "FINAL_SUMMARY.md"
    Write-File $sf $summary
    Update-State @{ status="FINISH"; is_complete=$true }

    Write-Host "`n=== 완료 ===" -ForegroundColor Green
    Write-Host "최종 보고서: $sf" -ForegroundColor Green
    Write-Host "프로젝트 파일: $script:WORKSPACE" -ForegroundColor Green
    return "DONE"
}

# ════════════════════════════════════════════════════════════
# 상태 머신 실행 (한 단계)
# ════════════════════════════════════════════════════════════
function Step-Once {
    if (-not (Test-Path $script:STATE_FILE)) { Stop-Fail "STATE.json 없음. -Goal로 시작하세요." }

    $st = Read-Json $script:STATE_FILE
    Write-Log "━━ 상태: $($st.status)  반복: $($st.iteration)/$($st.max_iterations) ━━"

    if ($st.iteration -ge $st.max_iterations) { Stop-Fail "최대 반복($($st.max_iterations)) 초과" }
    Update-State @{ iteration=($st.iteration+1) }

    switch ($st.status) {
        "INTAKE"      { Run-Intake }
        "CLARIFY"     { Run-Clarify }
        "REVISE"      { Run-Revise }
        "RESEARCH"       { Run-Research }
        "DEEP_RESEARCH"  { Run-DeepResearch }
        "HALLCHECK"      { Run-HallCheck }
        "PLAN"           { Run-Plan }
        "PARALLEL_EXECUTE" { Run-ParallelExecute }
        "DISPATCH"    { Run-Dispatch }
        "EXECUTE"     { Run-Execute }
        "UNIT_VERIFY" { Run-UnitVerify }
        "DECIDE"      { Run-Decide }
        "INTEGRATE"      { Run-Integrate }
        "CODEX_REVIEW"   { Run-CodexReview }
        "GEMINI_CHECK"   { Run-GeminiCheck }
        "CLAUDE_RECHECK" { Run-ClaudeRecheck }
        "INT_REVIEW"     { Run-IntegrationReview }
        "FINISH"      { return Run-Finish }
        "FAILED"      { Write-Log "FAILED 상태. STATE.json을 수정하거나 -Goal로 재시작." -Level "ERROR"; return "FAILED" }
        default       { Stop-Fail "알 수 없는 상태: $($st.status)" }
    }
    return "CONTINUE"
}

# ════════════════════════════════════════════════════════════
# 도움말
# ════════════════════════════════════════════════════════════
function Show-Help {
    Write-Host @"

╔══════════════════════════════════════════════════════╗
║   AI 중앙관리자  manager.ps1                         ║
║   Gemini(두뇌) + Claude(손) 이중 구조               ║
╠══════════════════════════════════════════════════════╣
║  흐름: INTAKE → RESEARCH → PLAN → DISPATCH           ║
║        → EXECUTE → UNIT_VERIFY → DECIDE              ║
║        → INTEGRATE → INT_REVIEW → FINISH             ║
╚══════════════════════════════════════════════════════╝

사용법:
  .\manager.ps1 -Goal "목표"        새 프로젝트 시작 (한 단계)
  .\manager.ps1 -Goal "목표" -Auto  완료까지 자동 실행
  .\manager.ps1 -Resume -Step       이어서 한 단계
  .\manager.ps1 -Resume -Auto       이어서 완료까지

역할:
  Gemini  → INTAKE 분석 / RESEARCH / PLAN / DECIDE / INT_REVIEW
  Claude  → EXECUTE (코드·문서·분석) / UNIT_VERIFY / INTEGRATE

안전장치:
  max_iterations       = 30  (STATE.json에서 수정 가능)
  max_retries_per_task = 3
  integrate_every_n    = 3   (N개 작업마다 자동 통합 테스트)
  CLI timeout          = $script:TIMEOUT_SEC 초

파일 구조:
  GOAL.md              사용자 목표
  INTAKE.md            프로젝트 유형 분석 결과
  RESEARCH.md          기술 리서치 결과
  PLAN.md              전체 계획
  ACCEPTANCE_CRITERIA.md  완료 기준
  STATE.json           현재 상태
  TASK_QUEUE.json      작업 큐
  tasks/               작업 지시서
  results/             실행 결과
  reviews/             검증 결과
  integration/         통합 테스트 보고서
  workspace/           실제 산출물 (코드 등)
  logs/                전체 실행 로그
"@ -ForegroundColor Cyan
}

# ════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════

if ($Help) { Show-Help; exit 0 }

# 모든 실행 경로에서 필수 폴더 보장 (Goal/Resume/Revise 공통)
if (-not (Test-Path $script:LOGS_DIR)) {
    New-Item -ItemType Directory -Path $script:LOGS_DIR -Force | Out-Null
}
if (-not (Test-Path $script:DEBUG_DIR)) {
    New-Item -ItemType Directory -Path $script:DEBUG_DIR -Force | Out-Null
}
# 세션 로그 초기화 (SESSION_LOG 가 아직 미설정이면)
if ($script:SESSION_LOG -eq "") {
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $script:SESSION_LOG = Join-Path $script:DEBUG_DIR "session_${ts}.log"
    $goalStr = if (Test-Path $script:GOAL_FILE) { [IO.File]::ReadAllText($script:GOAL_FILE,[Text.Encoding]::UTF8) } else { "(미설정)" }
    $header  = "=== AI Manager Session Start: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===`nGoal: $goalStr`nParams: Goal=$Goal Resume=$Resume Auto=$Auto`n"
    try { [IO.File]::WriteAllText($script:SESSION_LOG, $header, [Text.Encoding]::UTF8) } catch {}
}

# CLI 확인
foreach ($cli in @("gemini","claude","codex")) {
    if (-not (Test-Cmd $cli)) {
        Write-Host "WARNING: '$cli' 명령을 찾을 수 없습니다." -ForegroundColor Yellow
    }
}

# -Goal: 새 프로젝트 초기화 (이전 프로젝트 전체 정리)
if ($Goal) {
    # 이전 프로젝트 산출물 삭제 (Gemini가 구 파일을 읽어 혼동하는 것 방지)
    # 사용자 지정 WorkspaceDir은 삭제하지 않음 (사용자 소유 폴더)
    $defaultWs  = Join-Path $ROOT "workspace"
    $cleanWs    = if ($WorkspaceDir) { @() } else { @($defaultWs) }
    $cleanDirs  = $cleanWs + @($script:RESULTS_DIR, $script:REVIEWS_DIR,
                    $script:TASKS_DIR, $script:INTEG_DIR, $script:LOGS_DIR)
    $cleanFiles = @($script:INTAKE_FILE, $script:RESEARCH_FILE, $script:PLAN_FILE,
                    $script:CRITERIA_FILE, $script:CLARIFY_FILE, $script:REVISE_FILE,
                    $script:CLARIFY_QUEST_FILE)
    foreach ($d in $cleanDirs) {
        if (Test-Path $d) {
            Remove-Item $d -Recurse -Force -ErrorAction SilentlyContinue
            Write-Host "  정리: $d" -ForegroundColor DarkGray
        }
    }
    foreach ($f in $cleanFiles) {
        if (Test-Path $f) {
            Remove-Item $f -Force -ErrorAction SilentlyContinue
        }
    }

    Ensure-Dirs
    Write-File $script:GOAL_FILE "# Goal`n`n$Goal"

    $s = New-DefaultState
    $s.status = "INTAKE"
    Write-Json $script:STATE_FILE $s
    Write-Json $script:QUEUE_FILE ([PSCustomObject]@{ tasks=@() })

    Write-Log "새 프로젝트 시작: $Goal"
    Write-Log "파일 생성 완료: GOAL.md, STATE.json, TASK_QUEUE.json"
}
elseif ($Revise) {
    if (-not (Test-Path $script:STATE_FILE)) {
        Write-Host "오류: 수정할 프로젝트가 없습니다. 먼저 -Goal로 시작하세요." -ForegroundColor Red; exit 1
    }
    Write-File $script:REVISE_FILE "# 수정 지시`n`n$Revise"
    $s = Read-Json $script:STATE_FILE
    $s.status = "REVISE"
    $s.is_complete = $false
    Write-Json $script:STATE_FILE $s
    Write-Log "수정 지시 접수: $Revise"
}
elseif (-not $Resume) {
    Write-Host "오류: -Goal, -Revise, 또는 -Resume 이 필요합니다." -ForegroundColor Red
    Show-Help; exit 1
}

if (-not (Test-Path $script:STATE_FILE)) {
    Write-Host "오류: STATE.json 없음. -Goal로 시작하세요." -ForegroundColor Red; exit 1
}

# 실행 모드
if ($Auto) {
    Write-Log "=== Auto 모드 시작 ==="
    $i = 0
    while ($i -lt 200) {
        $i++
        $r = Step-Once
        if ($r -in @("DONE","FAILED")) { break }
        $cur = Read-Json $script:STATE_FILE
        if ($cur.status -in @("FINISH","FAILED") -or $cur.is_complete) { break }
    }
    Write-Log "=== Auto 모드 종료 (루프: $i) ==="
}
else {
    # -Step 또는 -Resume (단일 단계)
    $r = Step-Once
    Write-Log "=== 단계 완료: $r ==="
}
