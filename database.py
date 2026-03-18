from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from datetime import datetime

SQLALCHEMY_DATABASE_URL = "sqlite:///./savoria.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

class ReservationModel(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String)
    guests = Column(String)
    date = Column(String)
    time = Column(String, default="")
    message = Column(String)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.now)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_tables():
    Base.metadata.create_all(bind=engine)