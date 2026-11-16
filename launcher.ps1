param([switch]$DebugMode, [switch]$Doctor)
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
    foreach ($name in @('main.py', 'app/server.py', 'app/core/database.py', 'web/index.html')) {
      if (-not (Test-Path -LiteralPath (Join-Path $appDir $name) -PathType Leaf)) { throw ('Missing application file: ' + $name) }
    }
    # The official Windows embeddable distribution lives inside the project.
    # It never modifies system Python, PATH, registry or user installations.
    $portableDir = Join-Path $appDir 'runtime\python'
    $portableExe = Join-Path $portableDir 'python.exe'
    $program = $null
    if (Test-Path -LiteralPath $portableExe -PathType Leaf) {
      try {
        & $portableExe -c 'import sys, sqlite3, http.server; assert sys.version_info[:2] == (3,13)'
        if ($LASTEXITCODE -eq 0) { $program = $portableExe; Log 'Using existing portable Python.' }
      } catch { Log ('Portable Python is damaged: ' + $_.Exception.Message) }
    }
    if (-not $program) {
      $version = '3.13.9'
      $architecture = if ([Environment]::Is64BitOperatingSystem) { 'amd64' } else { 'win32' }
      $url = "https://www.python.org/ftp/python/$version/python-$version-embed-$architecture.zip"
      $runtimeRoot = Join-Path $appDir 'runtime'
      New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
      $zip = Join-Path $runtimeRoot 'python-download.zip'
      $stage = Join-Path $runtimeRoot ('python-stage-' + [Guid]::NewGuid().ToString('N'))
      Log ('Downloading portable Python ' + $version + ' from python.org...')
      try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing -MaximumRedirection 5
        New-Item -ItemType Directory -Path $stage | Out-Null
        Expand-Archive -LiteralPath $zip -DestinationPath $stage -Force
        $candidate = Join-Path $stage 'python.exe'
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw 'Python archive is incomplete.' }
        & $candidate -c 'import sys, sqlite3, http.server; assert sys.version_info[:2] == (3,13)'
        if ($LASTEXITCODE -ne 0) { throw 'Portable Python self-test failed.' }
        if (Test-Path -LiteralPath $portableDir) {
          $broken = Join-Path $runtimeRoot ('python-old-' + [Guid]::NewGuid().ToString('N'))
          Move-Item -LiteralPath $portableDir -Destination $broken
          try { Move-Item -LiteralPath $stage -Destination $portableDir }
          catch { Move-Item -LiteralPath $broken -Destination $portableDir; throw }
          Remove-Item -LiteralPath $broken -Recurse -Force -ErrorAction SilentlyContinue
        } else {
          Move-Item -LiteralPath $stage -Destination $portableDir
        }
        $program = $portableExe
        Log ('Portable Python ready: ' + $portableExe)
      } finally {
        Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue }
      }
    }
    Log ('Python: ' + $program)
    # The embeddable distribution isolates sys.path using python313._pth.
    # Add the project root there so main.py can import app modules directly.
    $pth = Join-Path $portableDir 'python313._pth'
    if (-not (Test-Path -LiteralPath $pth -PathType Leaf)) {
      throw 'Portable Python path configuration is missing: python313._pth'
    }
    $pthLines = @(Get-Content -LiteralPath $pth)
    if (-not ($pthLines | Where-Object { $_.Trim() -eq '..\..\' })) {
      Add-Content -LiteralPath $pth -Value '..\..\' -Encoding ASCII
    }
    $arguments = @('-u', (Join-Path $appDir 'main.py'))
    if ($Doctor) { $arguments = @('-u', (Join-Path $appDir 'doctor.py')) }
  }
  if ($Doctor -and (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw 'Doctor requires the source distribution with doctor.py, not the EXE-only bundle.'
  }
  Set-Location -LiteralPath $appDir
  $env:PORT = '0'
  $env:HOST = '127.0.0.1'
  Log (($(if ($Doctor) { 'Running Miyora doctor from: ' } else { 'Starting Miyora from: ' })) + $appDir)
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
