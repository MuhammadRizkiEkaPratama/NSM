"""Encrypt backup files before they are copied to an uncontrolled location.

`nsm.db` holds device credentials and its backup is copied to cloud storage nightly.
Stopping the copy would leave the only backup on the same disk as the data, so an
ENCRYPTED off-machine backup is preferred over a plaintext one that dies with the machine.

Cryptography choices:
* AES-256-GCM, not CBC: the authentication tag makes a tampered file fail loudly on open.
* scrypt derives the key from the passphrase (expensive in time and memory, so GPUs do not help).
* Random salt per file, stored in the file header.
* Random nonce per file; reusing a GCM nonce breaks its security entirely.
* Uses `cryptography`, already installed for paramiko and SNMP.

The passphrase lives in the Java `application.properties`, next to the MySQL and SMTP
credentials, and that file is NOT included in the backup zip.

WARNING: if this disk dies, `application.properties` dies with it and the encrypted backup
can never be opened. The passphrase MUST also be stored somewhere that survives the machine
(a password manager or paper); no code can replace that.
"""
import os
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

import config

# File magic, so an encrypted file can be recognized without opening it and the version can change safely.
AJAIB = b"NSMENC01"

GARAM_BYTE = 16
NONCE_BYTE = 12
# scrypt parameters. n=2^15 takes about 32 MB and a fraction of a second: slow enough to make
# guessing expensive, fast enough not to be noticed in the daily backup.
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1

# Read in chunks so a 10 MB file is not held twice in memory. GCM in `cryptography` works on
# the whole content, so chunks only apply to reading.
POTONGAN = 1024 * 1024


class TidakAdaFrasaSandi(Exception):
    """Passphrase is not set in application.properties."""


def frasa_sandi():
    """Get the passphrase from the Java properties file. None if not set."""
    props = config.baca_application_properties()
    value = (props.get("nsm.backup-passphrase") or "").strip()
    return value or None


def _kunci(sandi, garam):
    return Scrypt(salt=garam, length=32, n=SCRYPT_N, r=SCRYPT_R,
                  p=SCRYPT_P).derive(sandi.encode("utf-8"))


def enkripsi(sumber, tujuan, sandi):
    """Encrypt a file. Returns the size of the result in bytes.

    File layout:

        MAGIC (8) | salt (16) | nonce (12) | ciphertext+tag

    The header is also authenticated additional data, so altering the salt or nonce makes
    decryption fail instead of silently producing wrong content.
    """
    garam = os.urandom(GARAM_BYTE)
    nonce = os.urandom(NONCE_BYTE)
    kunci = _kunci(sandi, garam)

    with open(sumber, "rb") as f:
        content = f.read()

    header = AJAIB + garam + nonce
    locked = AESGCM(kunci).encrypt(nonce, content, header)

    # Written to a temporary file and then renamed: a half-written encrypted file would look
    # valid until someone tried to open it.
    temporary = tujuan + ".sedang-ditulis"
    with open(temporary, "wb") as f:
        f.write(header)
        f.write(locked)
    os.replace(temporary, tujuan)
    return os.path.getsize(tujuan)


def dekripsi(sumber, tujuan, sandi):
    """Decrypt a file. Raises if the passphrase is wrong OR the content was altered.

    The two cases are deliberately indistinguishable in the error message, so a guesser
    cannot learn that the passphrase was right.
    """
    with open(sumber, "rb") as f:
        data = f.read()
    if not data.startswith(AJAIB):
        raise ValueError("bukan berkas backup terenkripsi NSM")
    i = len(AJAIB)
    garam = data[i:i + GARAM_BYTE]
    nonce = data[i + GARAM_BYTE:i + GARAM_BYTE + NONCE_BYTE]
    header = data[:i + GARAM_BYTE + NONCE_BYTE]
    locked = data[i + GARAM_BYTE + NONCE_BYTE:]

    kunci = _kunci(sandi, garam)
    try:
        content = AESGCM(kunci).decrypt(nonce, locked, header)
    except Exception:
        raise ValueError(
            "gagal membuka: frasa sandi salah, atau berkasnya sudah berubah")

    temporary = tujuan + ".sedang-ditulis"
    with open(temporary, "wb") as f:
        f.write(content)
    os.replace(temporary, tujuan)
    return os.path.getsize(tujuan)


def terenkripsi(jalur):
    """True if this file is an NSM encrypted file."""
    try:
        with open(jalur, "rb") as f:
            return f.read(len(AJAIB)) == AJAIB
    except OSError:
        return False
