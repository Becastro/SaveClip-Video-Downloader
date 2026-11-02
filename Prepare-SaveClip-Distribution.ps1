$ErrorActionPreference = "Stop"

$dist = Join-Path $PSScriptRoot "dist"
$package = Join-Path $dist "SaveClip"
$sourceExe = Join-Path $package "SaveClip.exe"
$sourceInternal = Join-Path $package "_internal"
$targetExe = Join-Path $dist "SaveClip.exe"
$targetInternal = Join-Path $dist "_internal"
$stagedExe = Join-Path $dist "SaveClip.exe.new"
$stagedInternal = Join-Path $dist "_internal.new"

if (!(Test-Path -LiteralPath $sourceExe -PathType Leaf) -or
    !(Test-Path -LiteralPath $sourceInternal -PathType Container)) {
    throw "O pacote PyInstaller não contém SaveClip.exe e _internal."
}

if (Test-Path -LiteralPath $stagedInternal) {
    Remove-Item -LiteralPath $stagedInternal -Recurse -Force
}
if (Test-Path -LiteralPath $stagedExe) {
    Remove-Item -LiteralPath $stagedExe -Force
}

Copy-Item -LiteralPath $sourceInternal -Destination $stagedInternal -Recurse
Copy-Item -LiteralPath $sourceExe -Destination $stagedExe

if (Test-Path -LiteralPath $targetInternal) {
    Remove-Item -LiteralPath $targetInternal -Recurse -Force
}
Move-Item -LiteralPath $stagedInternal -Destination $targetInternal
Move-Item -LiteralPath $stagedExe -Destination $targetExe -Force

if (!(Test-Path -LiteralPath $targetExe -PathType Leaf) -or
    !(Test-Path -LiteralPath (Join-Path $targetInternal "frontend_dist\index.html") -PathType Leaf)) {
    throw "A distribuição SaveClip.exe não ficou completa."
}

Remove-Item -LiteralPath $package -Recurse -Force
Write-Output "Aplicativo pronto: $targetExe"
