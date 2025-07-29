import os
import time
import boto3

DEDUP_TABLE_NAME = os.environ["DEDUP_TABLE_NAME"]
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(DEDUP_TABLE_NAME)

def dedup_check_and_write(partition_key, dedup_id, ttl_hours=2):
    # Check for existing record
    resp = table.get_item(Key={"job_run_id": partition_key, "dedup_id": dedup_id})
    if "Item" in resp:
        return True  # Duplicate
    # Not a duplicate, write record
    expire_at = int(time.time()) + ttl_hours * 3600
    table.put_item(Item={"job_run_id": partition_key, "dedup_id": dedup_id, "expire_at": expire_at})
    return False