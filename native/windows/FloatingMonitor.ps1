param(
    [string]$PyzPath = "",
    [switch]$Demo,
    [switch]$NoWindows
)

if ([System.Threading.Thread]::CurrentThread.ApartmentState -ne "STA") {
    $argsList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-STA", "-File", $PSCommandPath)
    if ($PyzPath) { $argsList += @("-PyzPath", $PyzPath) }
    if ($Demo) { $argsList += "-Demo" }
    if ($NoWindows) { $argsList += "-NoWindows" }
    Start-Process powershell.exe -ArgumentList $argsList
    exit
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent (Split-Path -Parent $scriptDir)
if (-not $PyzPath) {
    $PyzPath = Join-Path $rootDir "ai-progress-monitor.pyz"
}

$logDir = Join-Path $env:LOCALAPPDATA "AI Progress Monitor"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "floating-monitor.log"

function Write-MonitorLog([string]$Message) {
    Add-Content -Path $logFile -Value ("{0:u} {1}" -f (Get-Date), $Message)
}

function Resolve-PythonCommand {
    $candidates = @(
        @("py", "-3"),
        @("python3"),
        @("python")
    )
    foreach ($candidate in $candidates) {
        $command = $candidate[0]
        if (Get-Command $command -ErrorAction SilentlyContinue) {
            return $candidate
        }
    }
    return $null
}

$monitorUrl = $null
$apiBase = $null
$apiToken = $null
$sessionCache = @()
$isExpanded = $false
$PollIntervalMilliseconds = 2000
$pythonCommand = Resolve-PythonCommand
if ($pythonCommand -eq $null) {
    Write-MonitorLog "Python was not found. Install Python 3 and try again."
}

$process = New-Object System.Diagnostics.Process
$process.StartInfo.FileName = if ($pythonCommand) { $pythonCommand[0] } else { "python" }
$process.StartInfo.UseShellExecute = $false
$process.StartInfo.RedirectStandardOutput = $true
$process.StartInfo.RedirectStandardError = $true
$process.StartInfo.CreateNoWindow = $true
$arguments = @()
if ($pythonCommand -and $pythonCommand.Length -gt 1) { $arguments += $pythonCommand[1..($pythonCommand.Length - 1)] }
$arguments += @("`"$PyzPath`"", "--host", "127.0.0.1", "--port", "8765", "--no-notifications")
if ($Demo) { $arguments += "--demo" }
if ($NoWindows) { $arguments += "--no-windows" }
$process.StartInfo.Arguments = ($arguments -join " ")

$outputHandler = [System.Diagnostics.DataReceivedEventHandler]{
    param($sender, $eventArgs)
    if (-not $eventArgs.Data) { return }
    Write-MonitorLog $eventArgs.Data
    if ($eventArgs.Data -match "AI Progress Monitor running at (http://[^ ]+)") {
        $script:monitorUrl = $Matches[1]
        if ($script:monitorUrl -match "^(http://[^?]+).*token=([^&]+)") {
            $script:apiBase = $Matches[1]
            $script:apiToken = $Matches[2]
        }
    }
}
$errorHandler = [System.Diagnostics.DataReceivedEventHandler]{
    param($sender, $eventArgs)
    if ($eventArgs.Data) { Write-MonitorLog $eventArgs.Data }
}
$process.add_OutputDataReceived($outputHandler)
$process.add_ErrorDataReceived($errorHandler)

try {
    if ($pythonCommand -ne $null) {
        [void]$process.Start()
        $process.BeginOutputReadLine()
        $process.BeginErrorReadLine()
    }
} catch {
    Write-MonitorLog ("Failed to start monitor: " + $_.Exception.Message)
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "AI Progress Monitor"
$form.Width = 260
$form.Height = 110
$form.StartPosition = "Manual"
$form.Left = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Right - $form.Width - 24
$form.Top = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Bottom - $form.Height - 24
$form.TopMost = $true
$form.ShowInTaskbar = $false

$title = New-Object System.Windows.Forms.Label
$title.Text = "AI Progress Monitor"
$title.Font = New-Object System.Drawing.Font("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
$title.AutoSize = $true
$title.Left = 12
$title.Top = 10
$form.Controls.Add($title)

$status = New-Object System.Windows.Forms.Label
$status.Text = if ($pythonCommand) { "Starting local monitor..." } else { "Python 3 was not found" }
$status.Left = 12
$status.Top = 38
$status.Width = 220
$status.Height = 22
$form.Controls.Add($status)

$list = New-Object System.Windows.Forms.FlowLayoutPanel
$list.Left = 12
$list.Top = 68
$list.Width = 300
$list.Height = 120
$list.AutoScroll = $true
$list.FlowDirection = "TopDown"
$list.WrapContents = $false
$list.Visible = $false
$form.Controls.Add($list)

$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Text = "AI Progress Monitor"
$notify.Visible = $true
$notify.Icon = [System.Drawing.SystemIcons]::Information
$menu = New-Object System.Windows.Forms.ContextMenuStrip
$showItem = $menu.Items.Add("Show Monitor")
$quitItem = $menu.Items.Add("Quit")
$notify.ContextMenuStrip = $menu
$notify.add_DoubleClick({ $form.Show(); $form.WindowState = "Normal"; $form.Activate() })
$showItem.add_Click({ $form.Show(); $form.WindowState = "Normal"; $form.Activate() })
$quitItem.add_Click({
    $notify.Visible = $false
    if ($process -and -not $process.HasExited) { $process.Kill() }
    [System.Windows.Forms.Application]::Exit()
})

function Move-CompanionToEdge {
    $form.Left = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Right - $form.Width - 24
    $form.Top = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Bottom - $form.Height - 24
}

function Set-CompanionMode([bool]$Expanded) {
    $script:isExpanded = $Expanded
    if ($Expanded) {
        $form.Width = 340
        $form.Height = 240
        $list.Visible = $true
    } else {
        $form.Width = 260
        $form.Height = 110
        $list.Visible = $false
    }
    Move-CompanionToEdge
}

function Toggle-CompanionMode {
    Set-CompanionMode (-not $script:isExpanded)
}

$form.add_Click({ Toggle-CompanionMode })
$title.add_Click({ Toggle-CompanionMode })
$status.add_Click({ Toggle-CompanionMode })

function Invoke-MonitorApi([string]$Path, [object]$Body = $null) {
    if (-not $script:apiBase -or -not $script:apiToken) { return $null }
    $url = "{0}{1}?token={2}" -f $script:apiBase, $Path, $script:apiToken
    if ($Body -eq $null) {
        return Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 2
    }
    $json = $Body | ConvertTo-Json -Depth 5
    return Invoke-RestMethod -Uri $url -Method Post -Body $json -ContentType "application/json" -TimeoutSec 2
}

function Add-SessionCard($session) {
    $isProcessOnly = $session.monitoring_level -eq "process_only"
    $card = New-Object System.Windows.Forms.Panel
    $card.Width = 286
    $card.Height = 86
    $card.BorderStyle = "FixedSingle"

    $name = New-Object System.Windows.Forms.Label
    $level = if ($isProcessOnly) { "process only" } else { "full" }
    $name.Text = "{0} [{1}] - {2}" -f $session.status, $level, $session.title
    $name.Left = 8
    $name.Top = 6
    $name.Width = 266
    $name.Height = 20
    $card.Controls.Add($name)

    $summary = New-Object System.Windows.Forms.Label
    $summary.Text = if ($isProcessOnly) { "Basic detection only. Use wrapper for content." } else { $session.summary }
    $summary.Left = 8
    $summary.Top = 28
    $summary.Width = 266
    $summary.Height = 22
    $card.Controls.Add($summary)

    $focus = New-Object System.Windows.Forms.Button
    $focus.Text = "Open"
    $focus.Left = 8
    $focus.Top = 54
    $focus.Width = 58
    $focus.Tag = $session.session_id
    $focus.add_Click({ Invoke-MonitorApi "/api/focus" @{ session_id = $this.Tag } | Out-Null })
    $card.Controls.Add($focus)

    if ($session.safe_action -and $session.safe_action.options) {
        $left = 72
        foreach ($option in $session.safe_action.options) {
            $button = New-Object System.Windows.Forms.Button
            $button.Text = $option
            $button.Left = $left
            $button.Top = 54
            $button.Width = 58
            $button.Tag = @{ session_id = $session.session_id; option = $option }
            $button.add_Click({
                Invoke-MonitorApi "/api/action" @{ session_id = $this.Tag.session_id; option = $this.Tag.option } | Out-Null
            })
            $card.Controls.Add($button)
            $left += 64
        }
    }

    $list.Controls.Add($card)
}

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = $PollIntervalMilliseconds
$timer.add_Tick({
    try {
        $payload = Invoke-MonitorApi "/api/sessions"
        if ($payload -eq $null) {
            $status.Text = "Waiting for local monitor..."
            return
        }
        $script:sessionCache = @($payload.sessions)
        $fullSessions = @($script:sessionCache | Where-Object { $_.monitoring_level -ne "process_only" })
        $processOnlySessions = @($script:sessionCache | Where-Object { $_.monitoring_level -eq "process_only" })
        $needs = @($fullSessions | Where-Object { $_.status -eq "needs_action" })
        if ($needs.Count -gt 0) {
            $status.Text = ("{0} needs your action" -f $needs.Count)
        } elseif ($fullSessions.Count -gt 0) {
            $status.Text = ("{0} sessions, {1} process-only" -f $fullSessions.Count, $processOnlySessions.Count)
        } else {
            $status.Text = ("{0} process-only detections" -f $processOnlySessions.Count)
        }
        $list.Controls.Clear()
        foreach ($session in $script:sessionCache) { Add-SessionCard $session }
    } catch {
        $status.Text = "Monitor is starting or unavailable"
        Write-MonitorLog $_.Exception.Message
    }
})
$timer.Start()

$form.add_FormClosing({
    if ($_.CloseReason -eq [System.Windows.Forms.CloseReason]::UserClosing) {
        $_.Cancel = $true
        $form.Hide()
    }
})

[System.Windows.Forms.Application]::Run($form)
