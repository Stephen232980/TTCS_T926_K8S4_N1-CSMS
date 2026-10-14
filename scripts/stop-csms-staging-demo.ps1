param(
    [string]$Server = 'azureadmin@23.100.101.246',
    [string]$KeyPath = 'C:\Users\LENOVO\.ssh\csms-staging-admin.pem'
)
$ErrorActionPreference = 'Stop'
& scp -i $KeyPath (Join-Path $PSScriptRoot 'staging_demo_host.py') "${Server}:/home/azureadmin/csms-staging-demo/"
if ($LASTEXITCODE -ne 0) { throw 'Không đồng bộ được bộ điều khiển simulator.' }
& ssh -i $KeyPath $Server 'python3 /home/azureadmin/csms-staging-demo/staging_demo_host.py stop'
if ($LASTEXITCODE -ne 0) { throw 'Chưa xác nhận dừng an toàn; kiểm tra log simulator.' }
