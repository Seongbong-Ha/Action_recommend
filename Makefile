.PHONY: setup run test dashboard demo all

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

dashboard:
	$(STREAMLIT) run app/dashboard.py

demo: run dashboard

all: setup run test
