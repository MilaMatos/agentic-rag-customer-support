# src/db/connection.py
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

load_dotenv()

_raw_url = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://admin:adminpassword@localhost:5432/nexus_knowledge",
)
DATABASE_URL = _raw_url.replace("postgresql+psycopg2://", "postgresql+psycopg://")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def criar_tabelas() -> None:
    # Garante registro dos modelos antes do create_all
    from src.db import models  # noqa: F401
    Base.metadata.create_all(bind=engine)