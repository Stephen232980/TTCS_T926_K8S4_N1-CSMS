param(
    [string]$Server = 'azureadmin@23.100.101.246',
    [string]$KeyPath = 'C:\Users\LENOVO\.ssh\csms-staging-admin.pem'
)
$ErrorActionPreference = 'Stop'
$remoteRoot = '/home/azureadmin/csms-staging-demo'
if (-not (Test-Path -LiteralPath $KeyPath)) { throw 'Không tìm thấy SSH key.' }
# Chỉ chạy sau khi bản đã review được merge/deploy. Script demo lấy từ image
# backend đang chạy; không tải file simulator local chưa review lên staging.
& scp -i $KeyPath (Join-Path $PSScriptRoot 'staging_demo_host.py') "${Server}:$remoteRoot/"
if ($LASTEXITCODE -ne 0) { throw 'Không cập nhật được trình quản lý demo.' }
& ssh -i $KeyPath $Server "python3 $remoteRoot/staging_demo_host.py update"
if ($LASTEXITCODE -ne 0) { throw 'Cập nhật demo chưa được xác nhận. Xem log; không chạy seed hoặc ép bỏ phiên/hold.' }
Write-Host 'Simulator đã cập nhật từ image backend; dữ liệu demo và profile được giữ lại.'
