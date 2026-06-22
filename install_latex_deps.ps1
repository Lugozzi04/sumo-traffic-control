# Installa le dipendenze LaTeX su Windows usando MiKTeX.
# MiKTeX scarica automaticamente i pacchetti mancanti quando compili.

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Invoke-WingetInstall {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PackageId
    )

    Write-Host "Provo a installare $PackageId con winget..."
    & winget install --id $PackageId --exact --silent --accept-package-agreements --accept-source-agreements
    return ($LASTEXITCODE -eq 0)
}

function Find-MiKTeXBinary {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BinaryName
    )

    $SearchRoots = @(
        $env:LOCALAPPDATA,
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)}
    ) | Where-Object { $_ -and (Test-Path $_) }

    foreach ($Root in $SearchRoots) {
        $Match = Get-ChildItem -Path $Root -Filter $BinaryName -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($Match) {
            return $Match.FullName
        }
    }

    return $null
}

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "Errore: winget non trovato."
    Write-Host "Installa 'App Installer' di Microsoft oppure scarica MiKTeX da:"
    Write-Host "  https://miktex.org/download"
    exit 1
}

$Installed = $false
foreach ($PackageId in @('ChristianSchenk.MiKTeX', 'MiKTeX.MiKTeX')) {
    if (Invoke-WingetInstall -PackageId $PackageId) {
        $Installed = $true
        break
    }
}

if (-not $Installed) {
    throw "Impossibile installare MiKTeX con winget."
}

$InitexmfPath = Find-MiKTeXBinary -BinaryName 'initexmf.exe'
if (-not $InitexmfPath) {
    $InitexmfCmd = Get-Command initexmf -ErrorAction SilentlyContinue
    if ($InitexmfCmd) {
        $InitexmfPath = $InitexmfCmd.Path
    }
}

if ($InitexmfPath) {
    & $InitexmfPath '--enable-installer'
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Avviso: non sono riuscito ad abilitare l'auto-installazione da CLI."
        Write-Host "Apri MiKTeX Console e attiva 'Always install missing packages on-the-fly'."
    }
} else {
    Write-Host "Apri MiKTeX Console e attiva 'Always install missing packages on-the-fly'."
}

$MpmPath = Find-MiKTeXBinary -BinaryName 'mpm.exe'
if (-not $MpmPath) {
    $MpmCmd = Get-Command mpm -ErrorAction SilentlyContinue
    if ($MpmCmd) {
        $MpmPath = $MpmCmd.Path
    }
}

if ($MpmPath) {
    & $MpmPath '--install=latexmk'
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Avviso: non sono riuscito a installare latexmk via mpm."
    }

    & $MpmPath '--install=biber-windows-x64'
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Avviso: non sono riuscito a installare biber via mpm."
    }
} else {
    Write-Host "Avviso: mpm non trovato. Apri MiKTeX Console e installa latexmk e biber."
}

Write-Host ""
Write-Host "Dipendenze installate."
Write-Host "Apri una nuova shell, poi compila con:"
Write-Host "  cd `"$ScriptDir\tesi`""
Write-Host "  latexmk -pdf -synctex=1 -interaction=nonstopmode -halt-on-error tesi.tex"
