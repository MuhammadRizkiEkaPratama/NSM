"""Move NSM to a dedicated monitoring account on a device.

The original monitoring account was in the `lxd` group on both VMs. `lxd` members can become
root WITHOUT a password, so credentials stored in plain text in `nsm.db` were equivalent to
root access. The account cannot simply be removed from the group: it is the only human
account and the only `sudo` member on those VMs.

Instead, create a separate monitoring account on the VM, then point NSM at it. This script
does only the LAST part (updating the row in `nsm.db`); creating the account on the VM is
manual, with steps in the `--panduan` output.

    python set_akun_pemantau.py --panduan
    python set_akun_pemantau.py --daftar
    python set_akun_pemantau.py --device 4 --user nsmro --kunci C:\\Users\\<user>\\.ssh\\nsm_vm
    python set_akun_pemantau.py --device 4 --user nsmro --sandi <password>

Run while the poller and uvicorn are STOPPED: it writes to `devices`.
"""
import sys

from database import SessionLocal
from models import Device

PANDUAN = """
LANGKAH DI VM [manual], sebelum menjalankan skrip ini
======================================================
Tempel SATU BARIS SATU BARIS, jangan sekaligus. Blok yang memuat baris `ssh`
akan ikut dijalankan di dalam sesi yang baru terbuka, dan hasilnya SSH
bersarang: satu `exit` tidak cukup untuk keluar.

1. Masuk ke VM dengan akun yang SEKARANG punya sudo:

       ssh nsm@192.168.56.101        (atau doni@192.168.56.103)

2. Periksa dulu siapa saja yang ada di grup sudo. Kalau hanya SATU nama,
   jangan pernah mencabut grup itu dari akun tersebut:

       getent group sudo

3. Buat akun pemantau tanpa sandi (hanya bisa masuk dengan kunci):

       sudo adduser --disabled-password --gecos "NSM baca" nsmro

4. HANYA di VM yang punya Apache (.103): beri akses baca log.
   Berkas log-nya `root:adm 640`, jadi grup `adm` memang diperlukan —
   diperiksa 8 Agustus, bukan diandaikan:

       sudo usermod -aG adm nsmro

5. Pasang kunci publik. Di LAPTOP, buat kuncinya lebih dulu:

       ssh-keygen -t ed25519 -f C:\\Users\\<user>\\.ssh\\nsm_vm -C nsm-baca -N ""

   Lalu tampilkan isinya dan salin:

       type C:\\Users\\<user>\\.ssh\\nsm_vm.pub

   Kembali di VM:

       sudo mkdir -p /home/nsmro/.ssh
       sudo nano /home/nsmro/.ssh/authorized_keys     (tempel, simpan)
       sudo chown -R nsmro:nsmro /home/nsmro/.ssh
       sudo chmod 700 /home/nsmro/.ssh
       sudo chmod 600 /home/nsmro/.ssh/authorized_keys

6. BUKTIKAN dari laptop, di jendela BARU, sebelum mengubah apa pun di NSM:

       ssh -i C:\\Users\\<user>\\.ssh\\nsm_vm nsmro@192.168.56.101 "id -Gn"

   Yang benar: keluar nama grup, dan TIDAK ada `sudo` maupun `lxd`.
   Kalau langkah ini gagal, BERHENTI. Jangan ubah NSM.

7. Barulah jalankan skrip ini untuk mengarahkan NSM ke akun baru.

8. Sesudah NSM terbukti masih mengumpulkan data (lihat halaman Kesehatan),
   akun lamamu boleh dicabut dari grup lxd — dan ini aman walau ia
   satu-satunya admin, karena grup `sudo`-nya tidak ikut hilang:

       sudo gpasswd -d nsm lxd          (atau doni)
"""


def main():
    if "--panduan" in sys.argv:
        print(PANDUAN)
        return 0

    db = SessionLocal()
    try:
        if "--daftar" in sys.argv or len(sys.argv) == 1:
            print("%-4s %-22s %-16s %-10s %-10s %s"
                  % ("id", "perangkat", "alamat", "platform", "akun", "kunci"))
            print("-" * 84)
            for d in db.query(Device).all():
                print("%-4s %-22s %-16s %-10s %-10s %s"
                      % (d.id, d.name[:22], d.ip_address, d.platform or "-",
                         d.username or "-", d.ssh_key_path or "(sandi)"))
            print("\nUbah dengan: --device <id> --user <nama> "
                  "[--kunci <jalur>|--sandi <sandi>]")
            print("Langkah di VM-nya: --panduan")
            return 0

        def ambil(bendera):
            if bendera in sys.argv:
                i = sys.argv.index(bendera)
                if i + 1 < len(sys.argv):
                    return sys.argv[i + 1]
            return None

        did = ambil("--device")
        user = ambil("--user")
        kunci = ambil("--kunci")
        sandi = ambil("--sandi")
        if not did or not user:
            print("Perlu --device dan --user. Lihat --daftar.")
            return 1
        if not kunci and not sandi:
            print("Perlu --kunci ATAU --sandi.")
            return 1

        d = db.query(Device).filter(Device.id == int(did)).first()
        if d is None:
            print(f"Perangkat id {did} tidak ada.")
            return 1

        print(f"Perangkat : {d.name} ({d.ip_address})")
        print(f"Akun      : {d.username}  ->  {user}")
        print("Cara masuk: " + ("kunci " + kunci if kunci else "sandi"))
        print()

        # Test first, then save. Saving first would leave NSM unable to log in by the time the
        # error is noticed, and fixing it would mean editing the database from a broken state.
        print("Menguji sambungan dengan akun baru sebelum menyimpan...")
        import paramiko
        cl = paramiko.SSHClient()
        cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            sambung = {"timeout": 15, "allow_agent": False,
                       "look_for_keys": False}
            if kunci:
                cl.connect(d.ip_address, username=user,
                           key_filename=kunci, **sambung)
            else:
                cl.connect(d.ip_address, username=user,
                           password=sandi, **sambung)
            _i, o, _e = cl.exec_command("id -Gn", timeout=15)
            group = o.read().decode(errors="replace").strip()
            cl.close()
        except Exception as e:
            print(f"  GAGAL tersambung: {e}")
            print("  Tidak ada yang diubah. Perbaiki dulu di VM-nya.")
            return 1

        print(f"  tersambung. grup akun baru: {group}")
        danger = [g for g in group.split() if g in ("sudo", "wheel", "admin",
                                                   "lxd", "docker")]
        if danger:
            # Warn, do not refuse: a privileged monitoring account is the problem being fixed, but the
            # operator may be moving to another temporary account and refusing would block legitimate work.
            print(f"  PERINGATAN: akun baru masih di grup istimewa: "
                  f"{', '.join(danger)}")
            print("  Ini persis temuan yang hendak diperbaiki. Lanjut? "
                  "Ketik 'ya' untuk menyimpan.")
            if input("  > ").strip().lower() != "ya":
                print("  Dibatalkan. Tidak ada yang diubah.")
                return 1

        d.username = user
        if kunci:
            d.ssh_key_path = kunci
            d.password = None
        else:
            d.password = sandi
            d.ssh_key_path = None
        db.commit()
        print("\nTersimpan. Nyalakan ulang poller & uvicorn, lalu buka")
        print("/admin/kesehatan untuk memastikan pengumpulan datanya jalan.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
