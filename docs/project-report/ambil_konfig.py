"""Mengambil running-config keempat perangkat Cisco untuk Lampiran laporan.

Seluruh rahasia disamarkan SEBELUM ditulis ke disk, bukan sesudahnya, supaya
tidak ada salinan tak tersensor yang sempat ada. Baca-saja, tidak ada satu pun
perintah konfigurasi yang dikirim.
"""
import re
import sys

sys.path.insert(0, r"C:\Users\<user>\NSM\backend")
from netmiko import ConnectHandler  # noqa: E402

DEV = [
    ("R1", "192.168.56.60", "Router Lokasi A"),
    ("SW-A", "192.168.56.61", "Switch Lokasi A"),
    ("R2", "192.168.20.1", "Router Lokasi B"),
    ("SW-B", "192.168.20.2", "Switch Lokasi B"),
]

# Tiap pola: (regex, pengganti). Ditulis eksplisit satu per satu supaya
# jelas apa yang disensor, bukan satu regex serba bisa yang sulit diperiksa.
SENSOR = [
    (re.compile(r"(secret \d )\S+"), r"\1<disamarkan>"),
    (re.compile(r"(password \d )\S+"), r"\1<disamarkan>"),
    (re.compile(r"(snmp-server community )\S+"), r"\1<disamarkan>"),
    (re.compile(r"(auth (?:md5|sha) )\S+"), r"\1<disamarkan>"),
    (re.compile(r"(priv (?:des|aes \d+) )\S+"), r"\1<disamarkan>"),
    (re.compile(r"(key(?:-string)? \d? ?)\S{8,}"), r"\1<disamarkan>"),
]


def samarkan(teks):
    keluar = []
    for baris in teks.splitlines():
        for pola, ganti in SENSOR:
            baris = pola.sub(ganti, baris)
        keluar.append(baris)
    return "\n".join(keluar)


def main():
    for nama, ip, peran in DEV:
        print(f"{nama} ({ip}) ...", end=" ", flush=True)
        try:
            c = ConnectHandler(device_type="cisco_ios", host=ip,
                               username="nsm", password="ExampleLabPass123",
                               fast_cli=False, conn_timeout=25)
            mentah = c.send_command("show running-config", read_timeout=90)
            c.disconnect()
        except Exception as e:
            print("GAGAL:", type(e).__name__, str(e)[:120])
            continue
        bersih = samarkan(mentah)
        jalur = rf"C:\Users\<user>\NSM\laporan\lampiran-data\{nama}-running-config.txt"
        with open(jalur, "w", encoding="utf-8") as f:
            f.write(bersih)
        jml_sensor = bersih.count("<disamarkan>")
        print(f"{len(bersih.splitlines())} baris, {jml_sensor} nilai disamarkan")


if __name__ == "__main__":
    main()
