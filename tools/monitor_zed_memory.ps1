<#
.SYNOPSIS
    Мониторинг памяти Zed Editor с предупреждением при достижении порога.

.DESCRIPTION
    Запускается в фоне, каждые N секунд проверяет память Zed.exe.
    При достижении порога (по умолчанию 3000 MB) выдаёт предупреждение.
    Ведёт лог в файл рядом со скриптом.

.PARAMETER ThresholdMB
    Порог срабатывания в MB (по умолчанию 3000)

.PARAMETER IntervalSec
    Интервал проверки в секундах (по умолчанию 30)

.PARAMETER LogFile
    Путь к файлу лога

.EXAMPLE
    # Запуск с порогом 2.5 GB и интервалом 15 сек
    .\monitor_zed_memory.ps1 -ThresholdMB 2500 -IntervalSec 15

.NOTES
    Автор: ManSio / MSCodeBase
    Дата: 2026-07-11
    Версия: 1.0
#>

param(
    [int]$ThresholdMB = 3000,
    [int]$IntervalSec = 30,
    [string]$LogFile = "$PSScriptRoot\zed_memory_monitor.log"
)

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] [$Level] $Message"
    Add-Content -Path $LogFile -Value $line
    Write-Host $line
}

function Get-ZedMemory {
    $procs = Get-Process -Name "Zed" -ErrorAction SilentlyContinue
    if (-not $procs) { return $null, $null }
    
    $total = 0
    $mainPid = $null
    foreach ($p in $procs) {
        $mb = [math]::Round($p.WorkingSet64 / 1MB, 0)
        $total += $mb
        if ($mb -gt 100) { $mainPid = $p.Id } # основной процесс (>100MB)
    }
    return $total, $mainPid
}

function Get-MemorySpike {
    param([int]$CurrentMB)
    # Возвращает +XX MB за последний интервал
    if (-not (Test-Path variable:script:lastMB)) { return $null }
    return $CurrentMB - $script:lastMB
}

# Инициализация
Write-Log "=== Zed Memory Monitor STARTED ==="
Write-Log "Threshold: ${ThresholdMB}MB, Interval: ${IntervalSec}s"
Write-Log "Log file: $LogFile"
Write-Log ""

$script:lastMB = $null
$crashDetected = $false
$checksSinceCrash = 0

while ($true) {
    $currentMB, $mainPid = Get-ZedMemory
    
    if ($currentMB -eq $null) {
        if (-not $crashDetected) {
            Write-Log "⚠️  Zed process NOT FOUND — possible crash or shutdown" "WARN"
            $crashDetected = $true
            # Воспроизводим звуковой сигнал
            [System.Console]::Beep(800, 500)
        }
        $script:lastMB = $null
        Start-Sleep -Seconds $IntervalSec
        continue
    }
    
    # Zed найден — сбрасываем флаг краша
    if ($crashDetected) {
        Write-Log "✅ Zed process RESTORED (PID: $mainPid, ${currentMB}MB)"
        $crashDetected = $false
        [System.Console]::Beep(400, 200)
    }
    
    $delta = Get-MemorySpike -CurrentMB $currentMB
    $deltaStr = if ($delta -ne $null) { "{+$($delta)MB}" } else { " (baseline)" }
    
    $level = if ($currentMB -gt $ThresholdMB) { "CRIT" } else { "INFO" }
    Write-Log "Zed PID:$mainPid ${currentMB}MB $deltaStr" $level
    
    # Если превышен порог — звуковое предупреждение + запись в лог
    if ($currentMB -gt $ThresholdMB) {
        $overPercent = [math]::Round(($currentMB / $ThresholdMB - 1) * 100, 0)
        Write-Log "🚨 MEMORY EXCEEDED! ${currentMB}MB > ${ThresholdMB}MB (${overPercent}% over)" "CRIT"
        [System.Console]::Beep(1000, 300)
        Start-Sleep -Milliseconds 200
        [System.Console]::Beep(1000, 300)
    }
    
    $script:lastMB = $currentMB
    Start-Sleep -Seconds $IntervalSec
}
