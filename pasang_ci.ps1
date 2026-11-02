# Install NSM CI as a Windows scheduled task.
#
# Local CI as a scheduled task, complementing the GitHub Actions workflow.
# The lab is entirely local (Windows laptop + VirtualBox VMs + GNS3); a cloud
# runner cannot reach any tested device and can only run the `murni` tier.
# What the project needs is an automatic answer to "has anything broken since I
# last looked". The pattern mirrors the existing "NSM Backup Incremental" task.
#
# Run as Administrator:
#     powershell -ExecutionPolicy Bypass -File C:\Users\<user>\NSM\pasang_ci.ps1
#
# Remove:
#     Unregister-ScheduledTask -TaskName "NSM CI" -Confirm:$false

$ErrorActionPreference = "Stop"

$NamaTugas = "NSM CI"
$Backend   = "C:\Users\<user>\NSM\backend"
$Python    = "$Backend\venv\Scripts\python.exe"
$Runner    = "$Backend\jalankan_ci.py"
$Laporan   = "$Backend\ci-hasil-terakhir.txt"

Write-Host "== 1/4 Memeriksa prasyarat =="
foreach ($p in @($Python, $Runner)) {
    if (-not (Test-Path $p)) { Write-Host "   BERHENTI: $p tidak ada."; exit 1 }
}
if (-not (Test-Path "$Backend\ci_manifest.json")) {
    Write-Host "   BERHENTI: ci_manifest.json belum ada."
    Write-Host "   Jalankan dulu: $Python $Backend\ci_klasifikasi.py"
    exit 1
}
Write-Host "   python, runner, dan manifest ada"

Write-Host "== 2/4 Membuktikan runner-nya benar-benar jalan SEBELUM dijadwalkan =="
# Run it once first: scheduling something never proven to work hides failures.
& $Python $Runner --mode murni --keluar-berkas $Laporan | Out-Null
$kode = $LASTEXITCODE
if ($kode -eq 2) {
    Write-Host "   BERHENTI: runner menjawab 2 (manifest bermasalah)."
    exit 1
}
Write-Host "   runner jalan, kode keluar $kode (0=hijau, 1=ada merah)"

Write-Host "== 3/4 Mendaftarkan tugas =="
# `murni` mode only: tests that need the live lab are not scheduled blindly, since
# the lab is often off and CI that is red whenever the VMs sleep gets ignored.
$aksi = New-ScheduledTaskAction -Execute $Python `
    -Argument "$Runner --mode murni --keluar-berkas `"$Laporan`"" `
    -WorkingDirectory $Backend

# 07:00, before the automation gate hours (08:00), so a failure is known before
# any automatic action may run.
$pemicu = New-ScheduledTaskTrigger -Daily -At 7:00AM

$setelan = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

if (Get-ScheduledTask -TaskName $NamaTugas -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $NamaTugas -Confirm:$false
    Write-Host "   tugas lama dicabut dulu"
}

Register-ScheduledTask -TaskName $NamaTugas -Action $aksi -Trigger $pemicu `
    -Settings $setelan `
    -Description "Menjalankan uji NSM tier 'murni' tiap pagi. Hasil di $Laporan." | Out-Null
Write-Host "   terdaftar: $NamaTugas, tiap hari 07:00"

Write-Host "== 4/4 Membuktikan tugasnya benar-benar bisa dipicu =="
# Verified by running it, not just by checking that it is registered.
Start-ScheduledTask -TaskName $NamaTugas
Start-Sleep -Seconds 10
$info = Get-ScheduledTaskInfo -TaskName $NamaTugas
Write-Host "   LastTaskResult: $($info.LastTaskResult)  (0=hijau, 1=ada uji merah)"
Write-Host "   LastRunTime   : $($info.LastRunTime)"

Write-Host ""
Write-Host "SELESAI."
Write-Host "Laporan terakhir selalu ada di: $Laporan"
Write-Host ""
Write-Host "CATATAN JUJUR: tugas ini TIDAK mengirim email. Menambahkannya"
Write-Host "berarti menaruh kredensial SMTP di jalur kedua di luar"
Write-Host "application.properties -- keputusan tersendiri yang belum diambil."
Write-Host "Untuk sekarang, hasilnya dibaca dari berkas laporan di atas."
