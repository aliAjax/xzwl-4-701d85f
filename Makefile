.PHONY: help install run migrate seed init reset test test-verbose clean db-status db-history new-migration lint

.DEFAULT_GOAL := help

PYTHON := python3
PIP := $(PYTHON) -m pip
ALEMBIC := $(PYTHON) -m alembic
UVICORN := $(PYTHON) -m uvicorn
PYTEST := $(PYTHON) -m pytest

help:
	@echo "Medical Equipment Rental System - Makefile Commands"
	@echo ""
	@echo "Usage:"
	@echo "  make install           Install project dependencies"
	@echo "  make run               Start the FastAPI development server"
	@echo "  make migrate           Run database migrations to latest version"
	@echo "  make seed              Insert seed data into the database"
	@echo "  make init              Run migrations + seed data (first-time setup)"
	@echo "  make reset             Reset database (drop all tables + re-migrate + seed)"
	@echo "  make db-status         Show current database migration status"
	@echo "  make db-history        Show migration history"
	@echo "  make new-migration     Generate new migration from model changes"
	@echo "  make test              Run all tests"
	@echo "  make test-verbose      Run tests with verbose output"
	@echo "  make clean             Remove temporary files and database"
	@echo ""

install:
	@echo "Installing dependencies..."
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Created .env from .env.example"; \
	fi
	$(PIP) install -r requirements.txt
	@echo "Dependencies installed successfully."

run:
	@echo "Starting FastAPI development server..."
	$(UVICORN) app.main:app --reload --host 0.0.0.0 --port 8000

migrate:
	@echo "Running database migrations..."
	$(ALEMBIC) upgrade head

seed:
	@echo "Seeding database..."
	$(PYTHON) init_db.py --seed-only

init:
	@echo "Initializing database (migrations + seed)..."
	$(PYTHON) init_db.py

reset:
	@echo "Resetting database..."
	@read -p "This will DELETE ALL DATA. Continue? [y/N] " confirm; \
	if [ "$$confirm" = "y" ] || [ "$$confirm" = "Y" ]; then \
		$(PYTHON) init_db.py --reset; \
	else \
		echo "Operation cancelled."; \
	fi

db-status:
	@echo "Database migration status:"
	$(ALEMBIC) current

db-history:
	@echo "Migration history:"
	$(ALEMBIC) history --verbose

new-migration:
	@read -p "Enter migration message: " msg; \
	$(ALEMBIC) revision --autogenerate -m "$$msg"

test:
	@echo "Running tests..."
	$(PYTEST) tests/ -v

test-verbose:
	@echo "Running tests with verbose output..."
	$(PYTEST) tests/ -v -s --tb=long

clean:
	@echo "Cleaning up..."
	@rm -f medical_rental.db
	@rm -rf .pytest_cache
	@rm -rf __pycache__
	@rm -rf app/__pycache__
	@rm -rf app/core/__pycache__
	@rm -rf app/models/__pycache__
	@rm -rf app/routers/__pycache__
	@rm -rf app/schemas/__pycache__
	@rm -rf tests/__pycache__
	@echo "Cleanup complete."
