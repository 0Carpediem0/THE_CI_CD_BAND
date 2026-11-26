param(
  [string]$Tag = "1.0.0",
  [string]$Registry = "",
  [switch]$LoadKind,
  [string]$KindCluster = ""
)

$Root = Split-Path -Parent $PSScriptRoot
$AppImage = if ($Registry) { "$Registry/office-wallet-app:$Tag" } else { "office-wallet-app:$Tag" }
$MockImage = if ($Registry) { "$Registry/office-wallet-mock:$Tag" } else { "office-wallet-mock:$Tag" }

docker build -t $AppImage "$Root\app"
docker build -t $MockImage "$Root\mock"
Write-Host "Built $AppImage"
Write-Host "Built $MockImage"

if ($LoadKind) {
  $kindArgs = @("load", "docker-image", $AppImage)
  if ($KindCluster) { $kindArgs += @("--name", $KindCluster) }
  kind @kindArgs
  $kindArgs[2] = $MockImage
  kind @kindArgs
  Write-Host "Loaded into kind"
}
