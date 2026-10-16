"""Copy recordings and the read-only history snapshot from S3 into /tmp at cold start."""
import os
from concurrent.futures import ThreadPoolExecutor

import boto3

bucket, root = os.environ["COOLPILOT_S3_BUCKET"], os.environ["COOLPILOT_DATA"]
s3 = boto3.client("s3")
objects = [o for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="data/")
           for o in page.get("Contents", []) if not o["Key"].endswith("/")]


def fetch(o):
    dest = os.path.join(root, o["Key"][len("data/"):])
    if os.path.exists(dest) and os.path.getsize(dest) == o["Size"]:
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    s3.download_file(bucket, o["Key"], dest)


with ThreadPoolExecutor(8) as pool:
    list(pool.map(fetch, objects))
print(f"fetched {len(objects)} objects to {root}", flush=True)
