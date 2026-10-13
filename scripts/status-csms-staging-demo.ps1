param(
    [switch]$Logs,
    [string]$Server = 'azureadmin@23.100.101.246',
    [string]$KeyPath = 'C:\Users\LENOVO\.ssh\csms-staging-admin.pem'
)
$ErrorActionPreference = 'Stop'
$demoAction = if ($Logs) { 'logs' } else { 'status' }
& scp -i $KeyPath (Join-Path $PSScriptRoot 'staging_demo_host.py') "${Server}:/home/azureadmin/csms-staging-demo/"
if ($LASTEXITCODE -ne 0) { throw 'Không đồng bộ được bộ điều khiển simulator.' }
& ssh -i $KeyPath $Server "python3 /home/azureadmin/csms-staging-demo/staging_demo_host.py $demoAction"
if ($LASTEXITCODE -ne 0) { throw 'Không đọc được trạng thái simulator staging.' }
