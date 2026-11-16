param([switch]$DebugMode)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root
$log = Join-Path $root 'launcher-diagnostic.txt'
function Log([string]$message) {
  $line = '[' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '] ' + $message
  Write-Host $line
  try { Add-Content -LiteralPath $log -Value $line -Encoding UTF8 } catch { Write-Host '[WARN] Cannot write launcher diagnostics.' }
}
try { Set-Content -LiteralPath $log -Value 'Miyora launcher diagnostics' -Encoding UTF8 } catch {}
$mutex = $null
$locked = $false
try {
  $hash = [BitConverter]::ToString(([System.Security.Cryptography.SHA256]::Create()).ComputeHash([Text.Encoding]::UTF8.GetBytes($root.ToLowerInvariant()))).Replace('-', '')
  $mutex = New-Object System.Threading.Mutex($false, ('Local\Miyora_' + $hash.Substring(0, 32)))
  try { $locked = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $locked = $true }
  if (-not $locked) { Log 'Miyora is already running from this directory.'; exit 0 }

  $appDir = $root
  $exe = Join-Path $appDir 'Miyora.exe'
  if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    $child = Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'Miyora.exe') -PathType Leaf } | Select-Object -First 1
    if ($child) { $appDir = $child.FullName; $exe = Join-Path $appDir 'Miyora.exe' }
  }
  if (Test-Path -LiteralPath $exe -PathType Leaf) {
    Log ('Using portable executable: ' + $exe)
    $program = $exe
    $arguments = @()
  } else {
    $appDir = $root
    if (-not (Test-Path -LiteralPath (Join-Path $appDir 'main.py') -PathType Leaf)) {
      $child = Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'main.py') -PathType Leaf } | Select-Object -First 1
      if ($child) { $appDir = $child.FullName }
    }
    foreach ($name in @('main.py', 'database.py', 'index.html')) {
      if (-not (Test-Path -LiteralPath (Join-Path $appDir $name) -PathType Leaf)) { throw ('Missing application file: ' + $name) }
    }
    $candidates = New-Object System.Collections.Generic.List[string]
    foreach ($cmd in @(Get-Command python.exe -All -ErrorAction SilentlyContinue)) {
      if ($cmd.Source) { [void]$candidates.Add($cmd.Source) }
    }
    if ($env:LOCALAPPDATA) {
      $base = Join-Path $env:LOCALAPPDATA 'Programs\Python'
      if (Test-Path -LiteralPath $base) {
        Get-ChildItem -LiteralPath $base -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue | ForEach-Object { [void]$candidates.Add((Join-Path $_.FullName 'python.exe')) }
      }
    }
    foreach ($base in @($env:ProgramFiles, [Environment]::GetEnvironmentVariable('ProgramFiles(x86)'))) {
      if ($base -and (Test-Path -LiteralPath $base)) {
        Get-ChildItem -LiteralPath $base -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue | ForEach-Object { [void]$candidates.Add((Join-Path $_.FullName 'python.exe')) }
      }
    }
    $program = $null
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
      if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
      try {
        $output = & $candidate -c 'import sys; print(sys.version_info.major,sys.version_info.minor)' 2>&1
        if ($LASTEXITCODE -eq 0 -and $output -match '^3 (9|1[0-9])$') { $program = $candidate; break }
      } catch { if ($DebugMode) { Log ('Rejected Python: ' + $candidate + ' ' + $_.Exception.Message) } }
    }
    if (-not $program) {
      Log 'No working Python >= 3.9 found.'
      $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
      if (-not $winget) { throw 'Install Python from https://www.python.org/downloads/windows/' }
      Log 'Installing Python 3.13 via winget (no repeated install if a working interpreter exists).'
      & $winget.Source install --id Python.Python.3.13 --exact --source winget --accept-package-agreements --accept-source-agreements
      if ($LASTEXITCODE -ne 0) { throw ('winget failed with exit code ' + $LASTEXITCODE) }
      $newPython = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
      if (Test-Path -LiteralPath $newPython) { $program = $newPython }
      else { throw 'Python installed. Restart start.bat to refresh installed Python paths.' }
    }
    Log ('Python: ' + $program)
    $arguments = @('-u', 'main.py')
  }
  Set-Location -LiteralPath $appDir
  $env:PORT = '0'
  $env:HOST = '127.0.0.1'
  Log ('Starting Miyora from: ' + $appDir)
  & $program @arguments
  $code = $LASTEXITCODE
  Log ('Miyora exited with code ' + $code)
  if ($code -ne 0) { exit 1 }
} catch {
  Log ('ERROR: ' + $_.Exception.Message)
  exit 1
} finally {
  if ($locked -and $mutex) { $mutex.ReleaseMutex() }
  if ($mutex) { $mutex.Dispose() }
}
