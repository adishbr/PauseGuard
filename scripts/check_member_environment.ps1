# Read-only diagnostic. Run in PowerShell from the PauseGuard project root.
# No installation, account login, network requests, changes or secret printing.
$ErrorActionPreference = 'Continue'
Write-Output 'PauseGuard Local Setup Diagnostic (no changes made)'
Write-Output 'NOTE: This only checks this one machine. Each of four members must run it individually.'
function Check-Command([string]$Name, [string]$VersionArgument) {
  $found = Get-Command $Name -ErrorAction SilentlyContinue
  if (-not $found) { Write-Output ('MISSING: ' + $Name); return }
  try {
    $version = (& $Name $VersionArgument 2>&1 | Select-Object -First 1)
    Write-Output ($Name + ': ' + $version)
  } catch { Write-Output ($Name + ': FOUND; version command failed') }
}
Check-Command 'git' '--version'
Check-Command 'node' '--version'
Check-Command 'npm' '--version'
Check-Command 'python' '--version'
Check-Command 'opencode' '--version'
if (Test-Path 'AGENTS.md') { Write-Output 'FOUND project AGENTS.md' } else { Write-Output 'MISSING project AGENTS.md' }
if (Test-Path '.vscode/extensions.json') { Write-Output 'FOUND extension recommendation list' } else { Write-Output 'MISSING extension recommendation list' }
if (Test-Path '.agents') { Write-Output 'FOUND project .agents folder' } else { Write-Output 'MISSING project .agents folder' }
Write-Output 'Check extension INSTALLATION from Antigravity UI Ctrl+Shift+X; this script does not claim to verify Antigravity extension state.'
