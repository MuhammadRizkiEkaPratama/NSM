from database import engine, SessionLocal, Base
from models import Device, StatusLog

Base.metadata.create_all(engine)

db = SessionLocal()
if db.query(Device).count() == 0:
    db.add(Device(name="Gateway WiFi", ip_address="192.168.1.1", device_type="router", location="Rumah"))
    db.add(Device(name="Laptop Sendiri", ip_address="192.168.1.43", device_type="pc", location="Rumah"))
    db.add(Device(name="Device Mati", ip_address="192.168.1.250", device_type="pc", location="Tes Down"))
    db.commit()
    print("Seed selesai")
else:
    print("Sudah ada data")
db.close()
