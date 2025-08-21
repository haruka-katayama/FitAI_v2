import pytest
from types import SimpleNamespace
from google.api_core.exceptions import BadRequest

from app.routers import dashboard


class DummyQueryJob:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error

    def result(self):
        if self.error:
            raise self.error
        return self.rows


def test_run_bq_with_fallback_schema_error(monkeypatch):
    """Fallback should trigger when primary raises column related error."""

    queries = []

    class DummyClient:
        def __init__(self):
            self.calls = 0

        def query(self, sql, job_config=None):
            queries.append(sql)
            if self.calls == 0:
                self.calls += 1
                raise BadRequest(
                    "Unrecognized name: image_base64",
                    errors=[{"message": "Unrecognized name: image_base64"}],
                )
            return DummyQueryJob(rows=[SimpleNamespace(dummy=1)])

    dummy_client = DummyClient()
    monkeypatch.setattr(dashboard, "bq_client", dummy_client)

    rows = dashboard._run_bq_with_fallback("primary_sql", "fallback_sql", [])

    assert len(rows) == 1
    assert queries == ["primary_sql", "fallback_sql"]


def test_run_bq_with_fallback_other_error(monkeypatch):
    """Non schema errors should propagate without using fallback."""

    queries = []

    class DummyClient:
        def query(self, sql, job_config=None):
            queries.append(sql)
            raise BadRequest(
                "Syntax error",
                errors=[{"message": "Syntax error"}],
            )

    dummy_client = DummyClient()
    monkeypatch.setattr(dashboard, "bq_client", dummy_client)

    with pytest.raises(BadRequest) as exc:
        dashboard._run_bq_with_fallback("primary_sql", "fallback_sql", [])

    assert "Syntax error" in str(exc.value)
    assert queries == ["primary_sql"]

