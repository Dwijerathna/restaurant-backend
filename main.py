from fastapi import FastAPI, Request, Depends, HTTPException
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
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv(dotenv_path=Path(__file__).parent / ".env")
create_tables()

RESTAURANT_NAME = os.getenv("RESTAURANT_NAME", "Savoria")

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
    time: str = ""
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
        hashed = get_password_hash(ADMIN_PASSWORD)
        verified = verify_password(form_data.password, hashed)
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
            time=data.time,
            message=data.message,
        )
        db.add(reservation)
        db.commit()

        try:
            requests.post("http://localhost:3001/notify", json={
                "name": data.name,
                "email": data.email,
                "guests": data.guests,
                "date": data.date,
                "time": data.time,
            }, timeout=2)
        except:
            pass

        sender = os.getenv("GMAIL_USER")
        password = os.getenv("GMAIL_PASSWORD")
        receiver = os.getenv("RESTAURANT_EMAIL", sender)

        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = receiver
        msg["Subject"] = f"New Reservation from {data.name} - {RESTAURANT_NAME}"

        body = f"""
        New Reservation Request - {RESTAURANT_NAME}:

        Name: {data.name}
        Email: {data.email}
        Guests: {data.guests}
        Date: {data.date}
        Time: {data.time}
        Message: {data.message}
        """

        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)

        customer_msg = MIMEMultipart()
        customer_msg["From"] = sender
        customer_msg["To"] = data.email
        customer_msg["Subject"] = f"Reservation Received - {RESTAURANT_NAME}"

        customer_body = f"""
        Dear {data.name},

        Thank you for your reservation at {RESTAURANT_NAME}!

        Here are your booking details:

        Date: {data.date}
        Time: {data.time}
        Guests: {data.guests}
        Special Requests: {data.message}

        We will confirm your reservation shortly.

        Warm regards,
        The {RESTAURANT_NAME} Team
        """

        customer_msg.attach(MIMEText(customer_body, "plain"))
        server.sendmail(sender, data.email, customer_msg.as_string())
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

    try:
        sender = os.getenv("GMAIL_USER")
        password = os.getenv("GMAIL_PASSWORD")

        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = reservation.email

        if update.status == "confirmed":
            msg["Subject"] = f"Reservation Confirmed - {RESTAURANT_NAME}"
            body = f"""
        Dear {reservation.name},

        Great news! Your reservation at {RESTAURANT_NAME} has been confirmed.

        Booking Details:
        Date: {reservation.date}
        Time: {reservation.time}
        Guests: {reservation.guests}

        We look forward to welcoming you!

        Warm regards,
        The {RESTAURANT_NAME} Team
            """
        else:
            msg["Subject"] = f"Reservation Update - {RESTAURANT_NAME}"
            body = f"""
        Dear {reservation.name},

        Unfortunately we are unable to accommodate your reservation at this time.

        Date requested: {reservation.date}
        Time: {reservation.time}
        Guests: {reservation.guests}

        Please contact us directly to find an alternative date.

        We apologize for the inconvenience.

        Warm regards,
        The {RESTAURANT_NAME} Team
            """

        msg.gross.attach(MIMEText(body, "plain"))
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print("Email error:", e)

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
    return {"message": f"{RESTAURANT_NAME} API is running!"}