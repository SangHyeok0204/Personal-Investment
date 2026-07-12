import csv
import os

from sqlalchemy import text

REQUIRED_COLUMNS = ["account_name", "ticker", "asset_name", "quantity"]


def _mark_import_failed(engine, import_id):
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE imports SET status='FAILED' WHERE id=:id"),
            {"id": import_id},
        )


def run(engine, job_id, payload, storage_dir, log_job):
    import_id = payload["import_id"]
    stored_filename = payload["stored_filename"]
    file_path = payload["file_path"]

    full_path = os.path.join(storage_dir, file_path)

    if not os.path.isfile(full_path):
        _mark_import_failed(engine, import_id)
        raise ValueError(f"CSV file not found: {file_path}")

    log_job(engine, job_id, "INFO", "validating", f"Validating {file_path}")

    with open(full_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        missing = [c for c in REQUIRED_COLUMNS if c not in fieldnames]
        if missing:
            _mark_import_failed(engine, import_id)
            raise ValueError(f"Required CSV columns are missing: {', '.join(missing)}")
        rows = list(reader)

    if not rows:
        _mark_import_failed(engine, import_id)
        raise ValueError("CSV file has no data rows")

    normalized_rows = []
    for i, row in enumerate(rows, start=1):
        quantity_raw = row.get("quantity")
        quantity_str = quantity_raw.strip() if quantity_raw else quantity_raw
        try:
            quantity = float(quantity_str)
        except (TypeError, ValueError):
            _mark_import_failed(engine, import_id)
            raise ValueError(f"Invalid quantity in row {i}: {quantity_raw!r}")
        if quantity < 0:
            _mark_import_failed(engine, import_id)
            raise ValueError(f"Invalid quantity in row {i}: {quantity_raw!r}")
        normalized_rows.append(
            {
                "account_name": row.get("account_name", ""),
                "ticker": row.get("ticker", ""),
                "asset_name": row.get("asset_name", ""),
                "quantity": quantity_str,
            }
        )

    log_job(engine, job_id, "INFO", "processing", f"Validated {len(normalized_rows)} rows")

    processed_dir = os.path.join(storage_dir, "processed")
    os.makedirs(processed_dir, exist_ok=True)
    processed_path = os.path.join(processed_dir, stored_filename)

    with open(processed_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(normalized_rows)

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE imports SET status='SUCCESS', row_count=:row_count WHERE id=:id"),
            {"row_count": len(normalized_rows), "id": import_id},
        )

    log_job(engine, job_id, "INFO", "done", f"Processed {len(normalized_rows)} rows")

    return {
        "row_count": len(normalized_rows),
        "processed_path": f"processed/{stored_filename}",
    }
