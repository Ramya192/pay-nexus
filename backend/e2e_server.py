"""Throwaway backend for the Playwright end-to-end tests (frontend/e2e).

Real FastAPI app and real auth/encryption-blob routes, but backed by a
temporary SQLite file instead of the Azure Postgres in .env, with the
login/registration rate limit off so many fresh accounts can be created. /chat
is NOT served meaningfully here -- the e2e specs mock it in the browser, so no
model call (and no Azure cost) ever happens.

Run: python e2e_server.py [port]   (default 8010)
"""

import os
import sys
import tempfile

import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.main import app
from db.database import Base, get_db
from security.rate_limit import limiter

db_path = os.path.join(tempfile.gettempdir(), "paynexus_e2e.sqlite")
if os.path.exists(db_path):
    os.remove(db_path)

engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def override_get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
limiter.enabled = False

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8010
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
