import csv
import json
import os
import uuid

from sqlalchemy import text

import main


def _insert_job(engine, job_type, payload):
    job_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO jobs (id, job_type, status, payload, created_at, updated_at) "
                "VALUES (:id, :job_type, 'PENDING', CAST(:payload AS JSONB), now(), now())"
            ),
            {"id": job_id, "job_type": job_type, "payload": json.dumps(payload)},
        )
    return job_id


def _get_job(engine, job_id):
    with engine.begin() as conn:
        row = conn.execute(text("SELECT * FROM jobs WHERE id=:id"), {"id": job_id}).mappings().first()
    return dict(row)


def _get_job_logs(engine, job_id):
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT * FROM job_logs WHERE job_id=:id"), {"id": job_id}
        ).mappings().all()
    return [dict(r) for r in rows]


def _get_import(engine, import_id):
    with engine.begin() as conn:
        row = conn.execute(text("SELECT * FROM imports WHERE id=:id"), {"id": import_id}).mappings().first()
    return dict(row)


def _insert_import_row(engine, stored_filename, file_path):
    import_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO imports (id, original_filename, stored_filename, file_path, "
                "file_size, status, created_at) "
                "VALUES (:id, 'orig.csv', :stored, :path, 100, 'PENDING', now())"
            ),
            {"id": import_id, "stored": stored_filename, "path": file_path},
        )
    return import_id


def _write_csv(storage_dir, stored_filename, header, rows):
    raw_dir = os.path.join(storage_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    file_path = f"raw/{stored_filename}"
    with open(os.path.join(storage_dir, file_path), "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    return file_path


def test_test_job_success(db, tmp_path):
    job_id = _insert_job(db, "TEST_JOB", {"hello": "world"})

    processed = main.run_one_cycle(db, str(tmp_path))

    assert processed is True
    job = _get_job(db, job_id)
    assert job["status"] == "SUCCESS"
    assert job["result"]["echo"] == {"hello": "world"}
    assert "processed_at" in job["result"]
    assert len(_get_job_logs(db, job_id)) > 0


def test_csv_import_success(db, tmp_path):
    storage_dir = str(tmp_path)
    stored_filename = "test.csv"
    file_path = _write_csv(
        storage_dir,
        stored_filename,
        ["account_name", "ticker", "asset_name", "quantity"],
        [
            ["Main Account", "000660", "SK Hynix", "10"],
            ["Main Account", "005930", "Samsung Electronics", "20"],
        ],
    )
    import_id = _insert_import_row(db, stored_filename, file_path)
    payload = {
        "import_id": str(import_id),
        "stored_filename": stored_filename,
        "file_path": file_path,
        "original_filename": "orig.csv",
    }
    job_id = _insert_job(db, "CSV_IMPORT", payload)

    processed = main.run_one_cycle(db, storage_dir)

    assert processed is True
    job = _get_job(db, job_id)
    imp = _get_import(db, import_id)
    assert job["status"] == "SUCCESS"
    assert job["result"]["row_count"] == 2
    assert job["result"]["processed_path"] == f"processed/{stored_filename}"
    assert imp["status"] == "SUCCESS"
    assert imp["row_count"] == 2
    assert os.path.isfile(os.path.join(storage_dir, "processed", stored_filename))


def test_csv_import_missing_column(db, tmp_path):
    storage_dir = str(tmp_path)
    stored_filename = "bad.csv"
    file_path = _write_csv(
        storage_dir,
        stored_filename,
        ["account_name", "asset_name", "quantity"],
        [["Main Account", "SK Hynix", "10"]],
    )
    import_id = _insert_import_row(db, stored_filename, file_path)
    payload = {
        "import_id": str(import_id),
        "stored_filename": stored_filename,
        "file_path": file_path,
        "original_filename": "orig.csv",
    }
    job_id = _insert_job(db, "CSV_IMPORT", payload)

    processed = main.run_one_cycle(db, storage_dir)

    assert processed is True
    job = _get_job(db, job_id)
    imp = _get_import(db, import_id)
    assert job["status"] == "FAILED"
    assert "ticker" in job["error_message"]
    assert imp["status"] == "FAILED"
