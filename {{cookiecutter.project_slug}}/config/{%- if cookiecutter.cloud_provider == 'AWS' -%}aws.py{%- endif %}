from __future__ import annotations

from functools import lru_cache

import boto3
from django.conf import settings


@lru_cache(maxsize=1)
def aws_session() -> boto3.Session:
    return boto3.Session(
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
        aws_session_token=settings.AWS_SESSION_TOKEN or None,
        region_name=settings.AWS_REGION,
    )


def aws_client(service_name: str, **kwargs):
    endpoint_url = settings.AWS_ENDPOINT_URL or None
    return aws_session().client(service_name, endpoint_url=endpoint_url, **kwargs)


def aws_resource(service_name: str, **kwargs):
    endpoint_url = settings.AWS_ENDPOINT_URL or None
    return aws_session().resource(service_name, endpoint_url=endpoint_url, **kwargs)
