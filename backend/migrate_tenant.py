r"""Package D: `tenant` table + `devices.tenant_id` column.

Adds one table and one column. Does NOT assign an owner to any device unless
`--tenant-bawaan` is given.

Why not assign automatically: ownership decides WHO can see what, which a
migration script should not decide silently. NULL `tenant_id` means
"unassigned" and is SAFE: `tenancy.py` filters on `tenant_id == <id>`, so
NULL rows are never visible to any tenant, only to callers WITHOUT a tenant
context (poller, CLI, platform admin), exactly the pre-tenancy behavior.

    py migrate_tenant.py                    add table + column only
    py migrate_tenant.py --tenant-bawaan    + create 1 tenant & assign old devices

`--tenant-bawaan` creates one tenant named "BSP (lab)" and makes it the owner
of EVERY device whose `tenant_id` is still NULL. That is correct for this lab
(all devices belong to one organization) but must be requested explicitly.

RUN A BACKUP AFTER THIS (see CONTRIBUTING.md).
"""
import sys

from sqlalchemy import inspect, select, text

import database
import models

NAMA_BAWAAN = "BSP (lab)"


def main():
    content_default = "--tenant-bawaan" in sys.argv
    mesin = database.engine
    ins = inspect(mesin)

    # ---- 1. tenant table ------------------------------------------------
    new_table = "tenant" not in ins.get_table_names()
    models.Tenant.__table__.create(mesin, checkfirst=True)
    print("  tabel tenant       %s" % ("DIBUAT" if new_table else "sudah ada"))

    # ---- 2. devices.tenant_id column ------------------------------------
    column = [c["name"] for c in ins.get_columns("devices")]
    if "tenant_id" in column:
        print("  devices.tenant_id  sudah ada")
    else:
        # NO FOREIGN KEY in the ALTER, deliberately.
        #
        # MySQL refuses to add a FOREIGN KEY to a populated table if any value does
        # not match; adding the column alone and letting the application enforce
        # integrity is simpler than one ALTER that could fail midway on a table
        # the poller is using.
        with mesin.begin() as c:
            c.execute(text("ALTER TABLE devices ADD COLUMN tenant_id INT NULL"))
            try:
                c.execute(text("CREATE INDEX ix_devices_tenant_id "
                               "ON devices (tenant_id)"))
            except Exception as e:              # noqa: BLE001
                print("  [CATATAN] indeks tidak dibuat: %s" % str(e)[:120])
        column = [c["name"] for c in inspect(mesin).get_columns("devices")]
        if "tenant_id" not in column:
            # "No error" is not proof of success.
            print("  [GAGAL] ALTER TABLE tidak melempar, tetapi kolomnya "
                  "TIDAK ADA sesudahnya.")
            return 1
        print("  devices.tenant_id  DITAMBAHKAN")

    # ---- 3. default tenant, if requested --------------------------------
    db = database.SessionLocal()
    try:
        n_null = len(db.execute(select(models.Device.id).where(
            models.Device.tenant_id.is_(None))).scalars().all())
        n_tenant = len(db.execute(select(models.Tenant.id)).scalars().all())
        print("  %d tenant terdaftar, %d device belum bertenant"
              % (n_tenant, n_null))

        if not content_default:
            if n_null:
                print()
                print("  %d device belum punya pemilik. Itu AMAN: mereka tidak"
                      % n_null)
                print("  terlihat oleh tenant mana pun, hanya oleh pemanggil")
                print("  tanpa konteks tenant (poller, CLI, admin platform).")
                print("  Tambahkan --tenant-bawaan untuk memberi mereka satu")
                print("  pemilik bernama %r." % NAMA_BAWAAN)
            return 0

        t = db.execute(select(models.Tenant).where(
            models.Tenant.nama == NAMA_BAWAAN)).scalars().first()
        if t is None:
            t = models.Tenant(nama=NAMA_BAWAAN, kontak=None,
                              kuota_device=None, aktif=True,
                              catatan="Dibuat migrate_tenant.py sebagai "
                                      "pemilik seluruh perangkat lab yang "
                                      "sudah ada sebelum Paket D.")
            db.add(t)
            db.commit()
            print("  tenant %r dibuat (id=%d)" % (NAMA_BAWAAN, t.id))
        else:
            print("  tenant %r sudah ada (id=%d)" % (NAMA_BAWAAN, t.id))

        filled = 0
        for d in db.execute(select(models.Device).where(
                models.Device.tenant_id.is_(None))).scalars().all():
            d.tenant_id = t.id
            filled += 1
        db.commit()

        remaining = len(db.execute(select(models.Device.id).where(
            models.Device.tenant_id.is_(None))).scalars().all())
        if remaining:
            print("  [GAGAL] masih ada %d device tanpa tenant sesudah "
                  "diisi." % remaining)
            return 1
        print("  %d device ditetapkan milik %r, 0 sisa" % (filled, NAMA_BAWAAN))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
