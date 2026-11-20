"""Create the clip bucket if missing (dev `make up`; idempotent). Retries while MinIO starts."""

import time

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from seetlu.core.config import get_settings


def ensure_bucket(attempts: int = 30, delay_s: float = 2.0) -> None:
    s = get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name="us-east-1",
    )
    for attempt in range(1, attempts + 1):
        try:
            existing = {b["Name"] for b in client.list_buckets().get("Buckets", []) if "Name" in b}
            if s.s3_bucket_clips not in existing:
                client.create_bucket(Bucket=s.s3_bucket_clips)
            print(f"bucket ready: {s.s3_bucket_clips}")
            return
        except (BotoCoreError, ClientError) as exc:
            if attempt == attempts:
                raise
            print(f"minio not ready ({exc}); retry {attempt}/{attempts}")
            time.sleep(delay_s)


if __name__ == "__main__":
    ensure_bucket()
