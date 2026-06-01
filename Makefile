.PHONY: setup run test dashboard all

PYTHON    := python
DBT       := dbt
STREAMLIT := streamlit

setup:
	docker-compose up -d
	$(PYTHON) -m pip install -r requirements.txt

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

all: setup run test
