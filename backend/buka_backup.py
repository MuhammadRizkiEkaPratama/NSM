"""Open an encrypted backup (`.enc`) into a plain zip.

    python buka_backup.py <file.enc> [target.zip]

The passphrase is read from `application.properties` (key
`nsm.backup-passphrase`). When restoring on ANOTHER machine, where that file
is absent, enter it by hand:

    python buka_backup.py <file.enc> --tanya

Read this before using encryption at all: a passphrase that exists ONLY on this
machine dies with it, and an encrypted backup without its key is just a random
file. Store the passphrase somewhere that does not die with the machine, such
as a password manager or paper.
"""
import getpass
import os
import sys

import sandi_backup


def main():
    arg = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not arg:
        print(__doc__)
        return 1

    source = arg[0]
    if not os.path.exists(source):
        print(f"Berkas tidak ada: {source}")
        return 1
    if not sandi_backup.terenkripsi(source):
        print(f"{source} bukan berkas terenkripsi NSM.")
        print("Kalau ia zip biasa, buka langsung tanpa skrip ini.")
        return 1

    destination = arg[1] if len(arg) > 1 else source[:-4] if source.endswith(".enc") \
        else source + ".zip"

    if "--tanya" in sys.argv:
        password = getpass.getpass("Frasa sandi backup: ")
    else:
        password = sandi_backup.frasa_sandi()
        if not password:
            print("`nsm.backup-passphrase` belum ada di application.properties.")
            print("Pakai --tanya untuk memasukkannya tangan.")
            return 1

    try:
        n = sandi_backup.dekripsi(source, destination, password)
    except ValueError as e:
        print(f"GAGAL: {e}")
        # No distinction between "wrong passphrase" and "file modified", on purpose:
        # telling a guesser the passphrase is right but the file is corrupt would leak
        # that the passphrase is right.
        return 1

    print(f"Terbuka: {destination}  ({n / 1024 / 1024:.2f} MB)")
    print("Isinya zip biasa. Periksa dengan: python uji_pulih_backup.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
