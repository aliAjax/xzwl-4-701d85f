from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from typing import Generator

from .config import settings

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def ensure_database_compatibility() -> None:
    inspector = inspect(engine)
    if "device_imports" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("device_imports")}
    if "skipped_count" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE device_imports "
                    "ADD COLUMN skipped_count INTEGER NOT NULL DEFAULT 0"
                )
            )

    if "contracts" in inspector.get_table_names():
        contract_columns = {column["name"] for column in inspector.get_columns("contracts")}
        if "commitment_batch_token" not in contract_columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE contracts "
                        "ADD COLUMN commitment_batch_token VARCHAR(100)"
                    )
                )
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_contracts_commitment_batch_token "
                        "ON contracts(commitment_batch_token)"
                    )
                )


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
