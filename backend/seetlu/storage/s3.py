"""S3/MinIO client and presigned URLs (docs/09: PUT 10 min, GET 15 min)."""

from functools import lru_cache
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from seetlu.core.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

PUT_TTL_S = 600
GET_TTL_S = 900


@lru_cache
def s3_client(public: bool = False) -> "S3Client":
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=(s.s3_public_endpoint or s.s3_endpoint) if public else s.s3_endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def presigned_put(key: str, content_type: str) -> str:
    return s3_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": get_settings().s3_bucket_clips, "Key": key, "ContentType": content_type},
        ExpiresIn=PUT_TTL_S,
    )


def presigned_get(key: str) -> str:
    return s3_client(public=True).generate_presigned_url(
        "get_object", Params={"Bucket": get_settings().s3_bucket_clips, "Key": key}, ExpiresIn=GET_TTL_S
    )
