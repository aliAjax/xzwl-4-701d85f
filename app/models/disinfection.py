from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from ..database import Base


class DisinfectionRecord(Base):
    __tablename__ = "disinfection_records"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    device = relationship("Device", back_populates="disinfection_records")

    disinfection_date = Column(DateTime(timezone=True), nullable=False)
    disinfectant_type = Column(String(100), nullable=False)
    disinfection_method = Column(String(100))
    duration_minutes = Column(Integer)
    operator_name = Column(String(100), nullable=False)

    temperature = Column(Float)
    concentration = Column(String(50))
    lot_number = Column(String(100))

    is_qualified = Column(Boolean, default=True)
    inspection_notes = Column(Text)

    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
