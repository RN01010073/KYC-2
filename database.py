"""
Database connection setup.

DATABASE_URL is read from the environment ONLY - never hardcode a real
connection string (with password) in this file or any other file in this
project. On Render: Dashboard -> your service -> Environment -> add
DATABASE_URL with your Supabase pooled connection string.

Locally: create a `.env` file (already in .gitignore) with:
    DATABASE_URL=postgresql://postgres.vrxmrwyyijgiyznyxcya:Nangia%40August%40@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres
    """

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Set it as an environment variable "
        "(Render: Environment tab; local: .env file). Never hardcode it in source."
    )

# Supabase's pooled (pgbouncer) connection works fine with pool_pre_ping;
# NullPool avoids holding onto stale connections behind the pooler.
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()