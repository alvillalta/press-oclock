from sqlmodel import Session, select

from app.core.db import engine
from app.models import User

with Session(engine) as session:
    user = session.exec(
        select(User).where(User.email == "pressoclock@gmail.com")
    ).first()

    print("USER:", user)