param(
    [string]$Server = 'azureadmin@23.100.101.246',
    [string]$KeyPath = 'C:\Users\LENOVO\.ssh\csms-staging-admin.pem'
)
$ErrorActionPreference = 'Stop'
$demoRoot = Join-Path (Split-Path $PSScriptRoot -Parent) '.local/csms-staging-demo'
$remoteRoot = '/home/azureadmin/csms-staging-demo'
if (-not (Test-Path -LiteralPath $KeyPath)) { throw 'Không tìm thấy SSH key.' }
& ssh -i $KeyPath $Server "mkdir -p $remoteRoot; chmod 700 $remoteRoot"
if ($LASTEXITCODE -ne 0) { throw 'Không kết nối được staging.' }
& ssh -i $KeyPath $Server "test -f $remoteRoot/accounts.json"
if ($LASTEXITCODE -ne 0) {
    if (-not (Test-Path -LiteralPath (Join-Path $demoRoot 'accounts.json'))) { throw 'Thiếu file tài khoản demo; không tự tạo lại mật khẩu.' }
    & scp -i $KeyPath (Join-Path $demoRoot 'accounts.json') "${Server}:$remoteRoot/accounts.json"
    if ($LASTEXITCODE -ne 0) { throw 'Không đưa được cấu hình tài khoản demo lên staging.' }
}
& scp -i $KeyPath (Join-Path $PSScriptRoot 'staging_demo_host.py') "${Server}:$remoteRoot/"
if ($LASTEXITCODE -ne 0) { throw 'Không đưa được simulator lên staging.' }
& ssh -i $KeyPath $Server "chmod 600 $remoteRoot/accounts.json; python3 $remoteRoot/staging_demo_host.py start"
if ($LASTEXITCODE -ne 0) { throw 'Demo staging chưa sẵn sàng; xem log bằng status-csms-staging-demo.ps1 -Logs.' }
& scp -i $KeyPath "${Server}:$remoteRoot/accounts.json" (Join-Path $demoRoot 'accounts.json')
if ($LASTEXITCODE -ne 0) { throw 'Demo đã chạy nhưng chưa tải được danh sách tài khoản.' }
Write-Host 'Demo staging: https://csms-staging.daominhtam2k6.id.vn/'
Write-Host "Tài khoản demo: $demoRoot\accounts.json"
Write-Host 'Dừng demo bằng scripts\stop-csms-staging-demo.ps1; không tắt backend staging.'
