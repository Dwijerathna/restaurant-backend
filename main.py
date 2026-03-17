from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session
from pathlib import Path
from database import get_db, create_tables, ReservationModel as DBReservation
from auth import verify_password, create_access_token, verify_token, get_password_hash, ADMIN_USERNAME, ADMIN_PASSWORD
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv(dotenv_path=Path(__file__).parent / ".env")
create_tables()

limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

class ReservationIn(BaseModel):
    name: str
    email: EmailStr
    guests: str = ""
    date: str
    message: str = ""

class StatusUpdate(BaseModel):
    status: str

def get_current_admin(token: str = Depends(oauth2_scheme)):
    username = verify_token(token)
    if username is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    return username

@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    try:
        print("Login attempt:", form_data.username)
        print("ADMIN_USERNAME:", ADMIN_USERNAME)
        print("ADMIN_PASSWORD:", ADMIN_PASSWORD)
        hashed = get_password_hash(ADMIN_PASSWORD)
        print("Hashed:", hashed)
        verified = verify_password(form_data.password, hashed)
        print("Verified:", verified)
        if form_data.username != ADMIN_USERNAME or not verified:
            raise HTTPException(status_code=400, detail="Incorrect username or password")
        token = create_access_token({"sub": form_data.username})
        return {"access_token": token, "token_type": "bearer"}
    except Exception as e:
        print("Login error:", e)
        raise

@app.post("/reserve")
@limiter.limit("5/minute")
async def reserve(request: Request, data: ReservationIn, db: Session = Depends(get_db)):
    try:
        reservation = DBReservation(
            name=data.name,
            email=data.email,
            guests=data.guests,
            date=data.date,
            message=data.message,
        )
        db.add(reservation)
        db.commit()

        sender = os.getenv("GMAIL_USER")
        password = os.getenv("GMAIL_PASSWORD")
        receiver = os.getenv("RESTAURANT_EMAIL", sender)

        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = receiver
        msg["Subject"] = f"New Reservation from {data.name}"

        body = f"""
        New Reservation Request:
        
        Name: {data.name}
        Email: {data.email}
        Guests: {data.guests}
        Date: {data.date}
        Message: {data.message}
        """

        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()

        return {"success": True, "message": "Reservation received!"}

    except Exception as e:
        print("Error:", e)
        return {"success": False, "message": str(e)}

@app.get("/admin/reservations")
async def get_reservations(db: Session = Depends(get_db), admin: str = Depends(get_current_admin)):
    reservations = db.query(DBReservation).order_by(DBReservation.created_at.desc()).all()
    return reservations

@app.patch("/admin/reservations/{id}")
async def update_status(id: int, update: StatusUpdate, db: Session = Depends(get_db), admin: str = Depends(get_current_admin)):
    reservation = db.query(DBReservation).filter(DBReservation.id == id).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")
    reservation.status = update.status
    db.commit()
    return {"success": True}

@app.delete("/admin/reservations/{id}")
async def delete_reservation(id: int, db: Session = Depends(get_db), admin: str = Depends(get_current_admin)):
    reservation = db.query(DBReservation).filter(DBReservation.id == id).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")
    db.delete(reservation)
    db.commit()
    return {"success": True}

@app.get("/")
def root():
    return {"message": "Savoria API is running!"}