param(
    [string]$CheckDate = (Get-Date).ToString("yyyy-MM-dd"),
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
if (-not $OutputDir) {
    $OutputDir = Join-Path $RepoRoot "data\training"
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$JsonPath = Join-Path $OutputDir "prod_quiz_learning_check_${CheckDate}_${Stamp}.json"
$MarkdownPath = Join-Path $OutputDir "prod_quiz_learning_check_${CheckDate}_${Stamp}.md"
$SshPath = "C:\Windows\System32\OpenSSH\ssh.exe"
$SshKey = "C:\Users\svens\.ssh\codex_fultons_ed25519"
$Remote = "ste@192.168.0.15"

$RemotePython = @'
import json
import os
import sqlite3

check_date = os.environ["CHECK_DATE"]
db_path = "/app/data/fultons.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

quiz = conn.execute(
    """
    SELECT quiz_date, status, generated_at, published_at, failure_reason
    FROM daily_quiz_sets
    WHERE quiz_date = ?
    """,
    (check_date,),
).fetchone()

attempts = conn.execute(
    """
    SELECT subject, difficulty, COUNT(*) AS attempts,
           SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END) AS passed,
           SUM(CASE WHEN passed = 0 THEN 1 ELSE 0 END) AS failed
    FROM daily_quiz_attempts
    WHERE quiz_date = ?
    GROUP BY subject, difficulty
    ORDER BY subject, difficulty
    """,
    (check_date,),
).fetchall()

failures = conn.execute(
    """
    SELECT COALESCE(failure_reason, '') AS reason, COUNT(*) AS count
    FROM daily_quiz_attempts
    WHERE quiz_date = ? AND passed = 0
    GROUP BY COALESCE(failure_reason, '')
    ORDER BY count DESC, reason ASC
    LIMIT 10
    """,
    (check_date,),
).fetchall()

questions = conn.execute(
    """
    SELECT daily_quiz_questions.subject,
           daily_quiz_questions.difficulty,
           daily_quiz_questions.question,
           daily_quiz_questions.correct_answer
    FROM daily_quiz_questions
    INNER JOIN daily_quiz_sets
        ON daily_quiz_sets.id = daily_quiz_questions.quiz_set_id
    WHERE daily_quiz_sets.quiz_date = ?
    ORDER BY daily_quiz_questions.subject, daily_quiz_questions.difficulty
    """,
    (check_date,),
).fetchall()

payload = {
    "check_date": check_date,
    "quiz": dict(quiz) if quiz else None,
    "attempts_by_slot": [dict(row) for row in attempts],
    "top_failure_reasons": [dict(row) for row in failures],
    "published_questions": [dict(row) for row in questions],
}
print(json.dumps(payload, indent=2, ensure_ascii=True))
'@

$SshArgs = @(
    "-i", $SshKey,
    "-p", "22",
    "-o", "BatchMode=yes",
    $Remote,
    "docker exec -i -e CHECK_DATE=$CheckDate fultons-quiz python -"
)

$Json = $RemotePython | & $SshPath @SshArgs
if ($LASTEXITCODE -ne 0) {
    throw "Production quiz learning check failed with exit code $LASTEXITCODE."
}

$Json | Set-Content -Path $JsonPath -Encoding UTF8
$Report = $Json | ConvertFrom-Json

$Lines = @()
$Lines += "# Production Quiz Learning Check"
$Lines += ""
$Lines += "- Date: $($Report.check_date)"
if ($Report.quiz) {
    $Lines += "- Status: $($Report.quiz.status)"
    $Lines += "- Published at: $($Report.quiz.published_at)"
    if ($Report.quiz.failure_reason) {
        $Lines += "- Failure reason: $($Report.quiz.failure_reason)"
    }
} else {
    $Lines += "- Status: missing quiz row"
}
$Lines += ""
$Lines += "## Attempts By Slot"
if ($Report.attempts_by_slot.Count -eq 0) {
    $Lines += "- No attempts recorded."
} else {
    foreach ($Slot in $Report.attempts_by_slot) {
        $Lines += "- $($Slot.subject) / $($Slot.difficulty): $($Slot.attempts) attempts, $($Slot.passed) passed, $($Slot.failed) failed"
    }
}
$Lines += ""
$Lines += "## Top Failure Reasons"
if ($Report.top_failure_reasons.Count -eq 0) {
    $Lines += "- No failed attempts recorded."
} else {
    foreach ($Failure in $Report.top_failure_reasons) {
        $Reason = if ($Failure.reason) { $Failure.reason } else { "(blank)" }
        $Lines += "- $($Failure.count)x $Reason"
    }
}
$Lines += ""
$Lines += "## Published Questions"
if ($Report.published_questions.Count -eq 0) {
    $Lines += "- No published questions found."
} else {
    foreach ($Question in $Report.published_questions) {
        $Lines += "- $($Question.subject) / $($Question.difficulty): $($Question.question) [$($Question.correct_answer)]"
    }
}
$Lines += ""

$Lines -join "`n" | Set-Content -Path $MarkdownPath -Encoding UTF8

Write-Host "Wrote $JsonPath"
Write-Host "Wrote $MarkdownPath"
