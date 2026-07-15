# 注册 Windows 计划任务：每天定时生成早报
# 用法（PowerShell）:  .\scripts\register_task.ps1            # 默认每天 08:00
#                     .\scripts\register_task.ps1 -Time 07:30
param(
    [string]$Time = "08:00",
    [string]$TaskName = "LLM-Daily-Report"
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$batPath = Join-Path $projectRoot "scripts\run_daily.bat"

$action = New-ScheduledTaskAction -Execute $batPath -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
# StartWhenAvailable: 错过触发时间（如未开机）则开机后尽快补跑
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)

try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop } catch {}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "每天生成大模型资讯早报 HTML"

Write-Host "已注册计划任务 [$TaskName]，每天 $Time 运行。"
Write-Host "手动测试:  Start-ScheduledTask -TaskName $TaskName"
