<#
  akses_ecanteen.ps1 - expose E-Canteen v2 to devices on the home LAN
  ==========================================================================

  THE PROBLEM
  -----------
  E-Canteen v2 runs in a VirtualBox VM at 192.168.56.103:8080. The
  192.168.56.0/24 network is host-only: it exists only INSIDE this laptop, so
  no other device (e.g. a phone) can ever reach it. It is not a phone or
  firewall issue; the address simply never leaves the laptop.

  THE APPROACH
  ------------
  The laptop becomes the single entry point:

      phone (192.168.1.x)  ->  laptop 192.168.1.3:80  ->  VM 192.168.56.103:8080

  Chosen over a bridged VM adapter because:
    - The VM is unchanged, so the MySQL grant
      `ecanteen_app@192.168.56.103` stays valid. Bridging would change the
      VM address and break that grant: E-Canteen would run but fail to read
      its database.
    - NSM keeps monitoring the VM at 192.168.56.103 as usual.
    - There is ONE entry point, here, so closing it is one command.

  Note: the forward passes TCP connections as-is, including the Host header.
  That matters because E-Canteen builds redirect URLs from it: sending
  `Host: 192.168.1.3` yields `Location: http://192.168.1.3/login`, not a
  192.168.56.x address the phone cannot reach.

  WHAT THIS SCRIPT DOES NOT DO
  ----------------------------
  Nothing is exposed to the internet. No router port forwarding, and there
  should be none. Access is opened to the home LAN only.

  USAGE (requires PowerShell "Run as Administrator")
  --------------------------------------------------
      .\akses_ecanteen.ps1 -Status      show current state
      .\akses_ecanteen.ps1 -Pasang      open access
      .\akses_ecanteen.ps1 -Lepas       close it again, cleanly
#>

[CmdletBinding()]
param(
    [switch]$Pasang,
    [switch]$Lepas,
    [switch]$Status,

    # Laptop port. 80 so the URL needs no port number (http://192.168.1.3),
    # which is easier to type on a phone.
    [int]$PortLaptop = 80,

    [string]$AlamatVM = "192.168.56.103",
    [int]$PortVM = 8080,

    # Only addresses in this range may connect. `LocalSubnet` means the currently
    # connected network, so it adapts if the home subnet changes.
    [string]$Dari = "LocalSubnet"
)

$NamaAturan = "E-Canteen V2 (LAN rumah)"

function Tulis($teks, $warna = "Gray") { Write-Host $teks -ForegroundColor $warna }

function Wajib-Admin {
    $admin = ([Security.Principal.WindowsPrincipal] `
              [Security.Principal.WindowsIdentity]::GetCurrent()
             ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $admin) {
        Tulis "Perlu PowerShell yang dijalankan sebagai Administrator." "Red"
        Tulis "Klik kanan PowerShell -> Run as administrator, lalu ulangi." "Red"
        exit 1
    }
}

function Lihat-Keadaan {
    Tulis "`n== Keadaan sekarang ==" "Cyan"

    $ip = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "Wi-Fi" `
           -ErrorAction SilentlyContinue).IPAddress
    $profil = (Get-NetConnectionProfile -InterfaceAlias "Wi-Fi" `
               -ErrorAction SilentlyContinue)
    Tulis ("  alamat laptop di Wi-Fi : " + ($ip  | Out-String).Trim())
    Tulis ("  nama jaringan          : " + ($profil.Name | Out-String).Trim())
    Tulis ("  profil jaringan        : " + ($profil.NetworkCategory | Out-String).Trim())

    Tulis "`n  penerusan port:"
    $pp = netsh interface portproxy show v4tov4 | Out-String
    if ($pp -match "\d") { Tulis $pp } else { Tulis "    (belum ada)" "DarkGray" }

    $aturan = Get-NetFirewallRule -DisplayName $NamaAturan -ErrorAction SilentlyContinue
    if ($aturan) {
        $port = ($aturan | Get-NetFirewallPortFilter).LocalPort
        $asal = ($aturan | Get-NetFirewallAddressFilter).RemoteAddress
        Tulis "`n  aturan firewall        : ADA (port $port, dari $asal, profil $($aturan.Profile), aktif=$($aturan.Enabled))" "Green"
    } else {
        Tulis "`n  aturan firewall        : belum ada" "DarkGray"
    }

    # Is E-Canteen actually up? If not, everything above is pointless, and the
    # symptom on the phone looks exactly like "access not opened yet".
    try {
        $uji = Test-NetConnection -ComputerName $AlamatVM -Port $PortVM `
               -InformationLevel Quiet -WarningAction SilentlyContinue
        if ($uji) { Tulis "  E-Canteen di VM        : hidup ($AlamatVM`:$PortVM)" "Green" }
        else      { Tulis "  E-Canteen di VM        : TIDAK menjawab ($AlamatVM`:$PortVM)" "Red" }
    } catch { Tulis "  E-Canteen di VM        : gagal diperiksa" "Red" }

    # Build the port part first, outside the quotes. PowerShell 5.1 cannot parse
    # double quotes inside $( ) that is itself inside double quotes, and the error
    # points at a different line.
    $ekor = ""
    if ($PortLaptop -ne 80) { $ekor = ":$PortLaptop" }
    if ($ip) { Tulis "`n  Alamat untuk HP: http://$ip$ekor" "Yellow" }
}

if ($Status -or (-not $Pasang -and -not $Lepas)) {
    Lihat-Keadaan
    if (-not $Pasang -and -not $Lepas -and -not $Status) {
        Tulis "`nPakai -Pasang untuk membuka, -Lepas untuk menutup.`n" "DarkGray"
    }
    return
}

Wajib-Admin

if ($Pasang) {
    # Do not grab a port another program is using. If port 80 is taken, the
    # forward fails silently and the phone only shows "cannot open", a symptom
    # shared with many other causes, so stop here with a clear message.
    $dipakai = Get-NetTCPConnection -State Listen -LocalPort $PortLaptop -ErrorAction SilentlyContinue
    if ($dipakai) {
        $proses = (Get-Process -Id $dipakai[0].OwningProcess -ErrorAction SilentlyContinue).ProcessName
        Tulis "Port $PortLaptop di laptop sudah dipakai oleh '$proses'." "Red"
        Tulis "Pilih port lain, misalnya: .\akses_ecanteen.ps1 -Pasang -PortLaptop 8081" "Red"
        exit 1
    }

    netsh interface portproxy add v4tov4 `
        listenaddress=0.0.0.0 listenport=$PortLaptop `
        connectaddress=$AlamatVM connectport=$PortVM | Out-Null
    Tulis "OK  penerusan dipasang: laptop:$PortLaptop -> $AlamatVM`:$PortVM" "Green"

    # listenaddress 0.0.0.0 listens on ALL network interfaces. Who may connect is
    # limited by the firewall rule below, not the listen address, so the forward
    # need not be rebuilt each time the laptop's Wi-Fi address changes.
    Get-NetFirewallRule -DisplayName $NamaAturan -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue

    New-NetFirewallRule `
        -DisplayName $NamaAturan `
        -Description "Akses E-Canteen v2 dari perangkat di jaringan rumah. Diteruskan ke VM $AlamatVM`:$PortVM." `
        -Direction Inbound -Action Allow -Protocol TCP `
        -LocalPort $PortLaptop -RemoteAddress $Dari `
        -Profile Private | Out-Null
    Tulis "OK  aturan firewall dibuat: TCP $PortLaptop, hanya dari $Dari, profil Private" "Green"

    $profil = Get-NetConnectionProfile -InterfaceAlias "Wi-Fi" -ErrorAction SilentlyContinue
    if ($profil -and $profil.NetworkCategory -ne "Private") {
        Tulis "`nPERHATIAN: Wi-Fi '$($profil.Name)' masih berprofil $($profil.NetworkCategory)," "Yellow"
        Tulis "sedangkan aturan tadi hanya berlaku di profil Private, jadi HP belum bisa masuk." "Yellow"
        Tulis "Jadikan Private (sekali saja, khusus jaringan rumah):" "Yellow"
        Tulis "    Set-NetConnectionProfile -InterfaceAlias 'Wi-Fi' -NetworkCategory Private" "Yellow"
        Tulis ""
        Tulis "Kenapa Private, bukan sekadar membatasi rentang alamat:" "DarkGray"
        Tulis "192.168.1.x adalah rentang paling umum di dunia — Wi-Fi kafe pun" "DarkGray"
        Tulis "sering memakainya. Aturan yang cuma dibatasi rentang alamat akan" "DarkGray"
        Tulis "ikut terbuka di sana. Profil Private hanya menempel pada jaringan" "DarkGray"
        Tulis "yang kamu tandai sendiri; jaringan asing tetap Public dan tertutup." "DarkGray"
    }

    Lihat-Keadaan
}

if ($Lepas) {
    netsh interface portproxy delete v4tov4 `
        listenaddress=0.0.0.0 listenport=$PortLaptop 2>$null | Out-Null
    Tulis "OK  penerusan port dilepas" "Green"

    $aturan = Get-NetFirewallRule -DisplayName $NamaAturan -ErrorAction SilentlyContinue
    if ($aturan) {
        $aturan | Remove-NetFirewallRule
        Tulis "OK  aturan firewall dihapus" "Green"
    } else {
        Tulis "    aturan firewall memang tidak ada" "DarkGray"
    }
    Lihat-Keadaan
}
