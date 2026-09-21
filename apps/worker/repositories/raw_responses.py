"""broker_api_raw_responses register (path relative to STORAGE_DIR + sha256)."""
import uuid

from sqlalchemy import text


def register_raw_response(
    conn, broker_id, job_id, api_category, endpoint_name, response_file_path, response_hash
):
    conn.execute(
        text(
            "INSERT INTO broker_api_raw_responses (id, broker_id, job_id, api_category, "
            "endpoint_name, response_file_path, response_hash, received_at, created_at) "
            "VALUES (:id, :broker_id, :job_id, :api_category, :endpoint_name, "
            ":response_file_path, :response_hash, now(), now())"
        ),
        {
            "id": uuid.uuid4(),
            "broker_id": broker_id,
            "job_id": job_id,
            "api_category": api_category,
            "endpoint_name": endpoint_name,
            "response_file_path": response_file_path,
            "response_hash": response_hash,
        },
    )
