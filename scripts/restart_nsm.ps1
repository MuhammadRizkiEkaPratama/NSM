<#
  restart_nsm.ps1 - restart all three NSM services, then verify they are serving.

  Everything is restarted rather than only what changed: a wrong guess about what needs a restart leaves an old process running stale code with no error.
  Restarting the poller leaves a few seconds gap in `status_logs`; `jeda.py` excludes poller downtime from the availability denominator.

  Usage:
      .\restart_nsm.ps1            restart everything, then check
      .\restart_nsm.ps1 -Status    check only, no restart
      .\restart_nsm.ps1 -TanpaJava skip Spring (mvnw is slowest)
#>

[CmdletBinding()]
param(
    [switch]$Status,
    [switch]$TanpaJava
)

$AKAR    = "C:\Users\<user>\NSM"
$PY      = "$AKAR\backend\venv\Scripts\python.exe"
$LOG     = "$env:TEMP\nsm-layanan"

function Tulis($t, $w = "Gray") { Write-Host $t -ForegroundColor $w }

function Proses-NSM {
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='java.exe'" |
        ForEach-Object {
            $c = $_.CommandLine
            $n = if ($c -like '*uvicorn*') { 'uvicorn' }
                 elseif ($c -like '*poller*') { 'poller' }
                 elseif ($c -like '*frontend*' -or $c -like '*spring-boot*') { 'spring' }
                 else { $null }
            if ($n) { [pscustomobject]@{ nama = $n; pid = $_.ProcessId; mulai = $_.CreationDate } }
        }
}

function Periksa {
    Tulis "`n== Keadaan ==" "Cyan"
    $p = Proses-NSM
    foreach ($n in 'poller', 'uvicorn', 'spring') {
        $ada = $p | Where-Object { $_.nama -eq $n }
        if ($ada) {
            $m = ($ada | Sort-Object mulai | Select-Object -First 1).mulai
            Tulis ("  {0,-9} jalan sejak {1:HH:mm:ss}" -f $n, $m) "Green"
        } else {
            Tulis ("  {0,-9} TIDAK JALAN" -f $n) "Red"
        }
    }

    # A running process is not necessarily a serving one; verify the answer, not the existence.
    Tulis "`n  jawaban:"
    foreach ($u in @(
        @{ n = "Python  /devices"; u = "http://localhost:8000/devices" },
        @{ n = "Python  /kesehatan"; u = "http://localhost:8000/kesehatan" },
        @{ n = "Spring  /login"; u = "http://localhost:8080/login" })) {
        try {
            $r = Invoke-WebRequest -Uri $u.u -TimeoutSec 15 -UseBasicParsing
            Tulis ("    {0,-20} {1}" -f $u.n, $r.StatusCode) "Green"
        } catch {
            Tulis ("    {0,-20} GAGAL" -f $u.n) "Red"
        }
    }

    # Judge the poller by its newest rows, not its process: a hung poller looks identical to a healthy one in the process list. Goes through `cek_segar.py` rather than opening the database file directly, since data now lives in MySQL.
    try {
        $t = & $PY "$AKAR\backend\cek_segar.py"
        if ($LASTEXITCODE -ne 0) {
            Tulis "    poller menulis      basis data TIDAK TERJANGKAU" "Red"
        } elseif ([int]$t -lt 0) {
            Tulis "    poller menulis      belum ada baris sama sekali" "Yellow"
        } elseif ([int]$t -lt 60) {
            Tulis "    poller menulis      $t dtk lalu" "Green"
        } else {
            Tulis "    poller menulis      $t dtk lalu (BASI)" "Red"
        }
    } catch { Tulis "    poller menulis      tidak bisa diperiksa" "Yellow" }
}

if ($Status) { Periksa; return }

New-Item -ItemType Directory -Force -Path $LOG | Out-Null

Tulis "== Menghentikan ==" "Cyan"
$p = Proses-NSM
if ($p) {
    foreach ($x in $p) {
        if ($TanpaJava -and $x.nama -eq 'spring') { continue }
        Stop-Process -Id $x.pid -Force -ErrorAction SilentlyContinue
        Tulis ("  {0,-9} PID {1} dihentikan" -f $x.nama, $x.pid)
    }
} else { Tulis "  (tidak ada yang jalan)" "DarkGray" }
Start-Sleep -Seconds 2

Tulis "`n== Menyalakan ==" "Cyan"

# `-u` is required for the poller: without it stdout is buffered when detached from a terminal and errors stay invisible until the process exits.
Start-Process -FilePath $PY -ArgumentList "-u", "poller.py" `
    -WorkingDirectory "$AKAR\backend" -WindowStyle Minimized `
    -RedirectStandardOutput "$LOG\poller.log" -RedirectStandardError "$LOG\poller.err"
Tulis "  poller    dinyalakan  ($LOG\poller.log)"

Start-Process -FilePath $PY -ArgumentList "-m", "uvicorn", "main:app", "--port", "8000" `
    -WorkingDirectory "$AKAR\backend" -WindowStyle Minimized `
    -RedirectStandardOutput "$LOG\uvicorn.log" -RedirectStandardError "$LOG\uvicorn.err"
Tulis "  uvicorn   dinyalakan  ($LOG\uvicorn.log)"

if (-not $TanpaJava) {
    # Lab CA truststore: without it nobody can log in. Since LDAP requires StartTLS, Spring must verify the `.101` certificate issued by the lab CA. Java does not know that CA, so the handshake fails (PKIX path building failed) and the login page misleadingly reports a wrong username or password for every account.
    #
    # The truststore is a copy of the JDK `cacerts` plus the lab CA; a lab-CA-only truststore would make Java distrust all public CAs.
    $TS = "$AKAR\nsm-truststore.jks"
    if (Test-Path $TS) {
        $env:JAVA_TOOL_OPTIONS = "-Djavax.net.ssl.trustStore=$TS " +
                                 "-Djavax.net.ssl.trustStorePassword=changeit"
    } else {
        Tulis "  !! nsm-truststore.jks TIDAK ADA - login akan GAGAL untuk semua akun" "Red"
        Tulis "     buat ulang: keytool -importcert -alias bsp-lab-ca -file bsp-lab-ca.crt" "Red"
        Tulis "                 -keystore nsm-truststore.jks -storepass changeit" "Red"
    }
    Start-Process -FilePath "$AKAR\frontend\mvnw.cmd" -ArgumentList "-o", "spring-boot:run" `
        -WorkingDirectory "$AKAR\frontend" -WindowStyle Minimized `
        -RedirectStandardOutput "$LOG\spring.log" -RedirectStandardError "$LOG\spring.err"
    Tulis "  spring    dinyalakan  ($LOG\spring.log)"
}

# Spring is slowest; wait until it actually answers instead of sleeping a fixed time, which gives false failures.
Tulis "`n  menunggu layanan siap..." "DarkGray"
$batas = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $batas) {
    $siap = $true
    foreach ($u in @("http://localhost:8000/devices",
                     $(if ($TanpaJava) { $null } else { "http://localhost:8080/login" }))) {
        if (-not $u) { continue }
        try { Invoke-WebRequest -Uri $u -TimeoutSec 5 -UseBasicParsing | Out-Null }
        catch { $siap = $false }
    }
    if ($siap) { break }
    Start-Sleep -Seconds 3
}

Periksa
