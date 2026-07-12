import uuid
from pathlib import Path

from app.core.config import settings
from app.models import Import, Job

CSV_CONTENT = b"account_name,ticker,asset_name,quantity\nMain Account,000660,SK Hynix,10\n"


def test_import_csv_success(client, db):
    response = client.post(
        "/api/v1/imports/csv",
        files={"file": ("portfolio.csv", CSV_CONTENT, "text/csv")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["original_filename"] == "portfolio.csv"
    job_id = uuid.UUID(body["job_id"])
    import_id = uuid.UUID(body["import_id"])

    record = db.get(Import, import_id)
    assert record is not None
    assert record.status == "PENDING"
    assert record.job_id == job_id
    assert record.file_size == len(CSV_CONTENT)
    assert record.file_path.startswith("raw/")

    job = db.get(Job, job_id)
    assert job.job_type == "CSV_IMPORT"
    assert job.status == "PENDING"
    assert job.payload["import_id"] == body["import_id"]
    assert job.payload["original_filename"] == "portfolio.csv"
    assert job.payload["file_path"] == f"raw/{job.payload['stored_filename']}"

    stored_path = Path(settings.STORAGE_DIR) / "raw" / job.payload["stored_filename"]
    assert stored_path.exists()
    assert stored_path.read_bytes() == CSV_CONTENT


def test_import_csv_extension_case_insensitive(client):
    response = client.post(
        "/api/v1/imports/csv",
        files={"file": ("PORTFOLIO.CSV", CSV_CONTENT, "text/csv")},
    )
    assert response.status_code == 201


def test_import_csv_wrong_extension(client):
    response = client.post(
        "/api/v1/imports/csv",
        files={"file": ("data.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FILE_TYPE"


def test_import_csv_empty(client):
    response = client.post(
        "/api/v1/imports/csv",
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMPTY_FILE"
