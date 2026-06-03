.PHONY: setup run seed test test-unit evaluate reset-data dashboard demo all

ifneq (,$(wildcard .env))
  include .env
  export
endif

PYTHON    := python
DBT       := dbt
STREAMLIT := streamlit

setup:
	docker-compose up -d
	$(PYTHON) -m pip install -r requirements.txt
	$(DBT) deps --project-dir dbt_project --profiles-dir dbt_project

run:
	$(PYTHON) -m src.database
	$(PYTHON) -m src.ingest
	$(DBT) run --project-dir dbt_project --profiles-dir dbt_project --select staging
	$(PYTHON) -m src.extract
	$(DBT) run --project-dir dbt_project --profiles-dir dbt_project --select marts

test:
	$(DBT) test --project-dir dbt_project --profiles-dir dbt_project

test-unit:
	$(PYTHON) -m pytest tests/ -v

evaluate:
	$(PYTHON) -m src.evaluate

seed:
	$(PYTHON) -m src.seed
	$(DBT) run --project-dir dbt_project --profiles-dir dbt_project --select staging marts

reset-data:
	$(PYTHON) -c "from src.database import reset_db; reset_db()"

dashboard: reset-data
	$(STREAMLIT) run app/dashboard.py

demo:
	$(MAKE) run
	$(MAKE) test
	$(MAKE) evaluate
	$(MAKE) seed
	$(STREAMLIT) run app/dashboard.py

all: setup run test
