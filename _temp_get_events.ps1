# Get Application Errors
$app = Get-WinEvent -LogName Application -MaxEvents 200 | Where-Object { $_.LevelDisplayName -eq 'Error' }
Write-Output "=== APPLICATION ERRORS ==="
$app | Format-Table TimeCreated, Id, ProviderName, @{N='Msg';E={$_.Message.Substring(0,[Math]::Min(200,$_.Message.Length))}} -AutoSize

# Get System Critical Events
$sys = Get-WinEvent -LogName System -MaxEvents 200 | Where-Object { $_.Id -eq 41 -or $_.Id -eq 1001 -or $_.Id -eq 1000 }
Write-Output "`n=== SYSTEM EVENTS (41=Kernel-Power, 1001= BugCheck, 1000=AppError) ==="
$sys | Format-Table TimeCreated, Id, LevelDisplayName, @{N='Msg';E={$_.Message.Substring(0,[Math]::Min(150,$_.Message.Length))}} -AutoSize
