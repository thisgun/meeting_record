<#
.SYNOPSIS
  meeting_api PHP 플러그인 정본 → 그누보드5 배포본 동기화.

.DESCRIPTION
  repo의 정본(g5_meeting_api/plugin/meeting_api/*.php)을 실제 동작하는 그누보드5
  plugin 폴더로 복사한다. main을 pull/merge한 뒤 이 스크립트를 실행하지 않으면
  배포본이 구버전으로 남아 신규 엔드포인트가 404로 실패할 수 있다(수동 복사 누락 방지).

  config.local.php(환경별 토큰·경로)는 절대 덮어쓰지 않는다.

.PARAMETER Target
  배포 대상 plugin 폴더. 기본: C:\dev2\gnuboard5\plugin\meeting_api

.PARAMETER DryRun
  실제 복사 없이 대상 파일만 출력.

.EXAMPLE
  pwsh scripts/deploy_plugin.ps1
  pwsh scripts/deploy_plugin.ps1 -Target D:\web\gnuboard5\plugin\meeting_api
  pwsh scripts/deploy_plugin.ps1 -DryRun
#>
param(
    [string]$Target = "C:\dev2\gnuboard5\plugin\meeting_api",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$src = Resolve-Path (Join-Path $PSScriptRoot "..\g5_meeting_api\plugin\meeting_api")
if (-not (Test-Path $Target)) {
    Write-Error "배포 대상 폴더가 없습니다: $Target"
    exit 1
}

Write-Host "정본:   $src"
Write-Host "배포본: $Target"
Write-Host ("-" * 60)

# config.local.php(환경별 비밀)는 보존. 그 외 모든 .php와 .example을 복사.
$files = Get-ChildItem "$src\*" -File -Include *.php, *.example |
    Where-Object { $_.Name -ne "config.local.php" }

$copied = 0
foreach ($f in $files) {
    if ($DryRun) {
        Write-Host "  [dry-run] $($f.Name)"
    } else {
        Copy-Item $f.FullName $Target -Force
        Write-Host "  복사: $($f.Name)"
    }
    $copied++
}

# 배포본에만 있고 정본에 없는 .php는 정본에서 삭제된 엔드포인트일 수 있으니 경고만.
$srcNames = $files | ForEach-Object { $_.Name }
$orphans = Get-ChildItem "$Target\*.php" -File |
    Where-Object { $_.Name -ne "config.local.php" -and $srcNames -notcontains $_.Name }
foreach ($o in $orphans) {
    Write-Warning "배포본에만 존재(정본에 없음): $($o.Name) — 정본에서 삭제됐다면 수동 제거 검토"
}

Write-Host ("-" * 60)
$verb = if ($DryRun) { "복사 예정" } else { "복사 완료" }
Write-Host "${verb}: $copied 개 파일"
if (-not $DryRun) {
    Write-Host "config.local.php는 보존됨. 신규 설치라면 config.local.php.example을 복사해 작성하세요."
}
