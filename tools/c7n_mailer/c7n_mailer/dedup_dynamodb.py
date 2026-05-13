import os
import time
import boto3
import logging

# Get logger for error handling
logger = logging.getLogger(__name__)

# Initialize with error handling
try:
    DEDUP_TABLE_NAME = os.environ.get("DEDUP_TABLE_NAME")
    if DEDUP_TABLE_NAME:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(DEDUP_TABLE_NAME)
        DEDUP_ENABLED = True
        logger.info(f"Deduplication enabled with table: {DEDUP_TABLE_NAME}")
    else:
        DEDUP_ENABLED = False
        logger.warning("DEDUP_TABLE_NAME environment variable not set. Deduplication disabled.")
except Exception as e:
    DEDUP_ENABLED = False
    logger.warning(f"DynamoDB table not accessible. Deduplication disabled. Error: {e}")

def dedup_check_and_write(partition_key, dedup_id, ttl_hours=2):
    """
    Check if a notification has already been sent and write a record if not.
    
    Args:
        partition_key (str): The job run identifier (execution_start timestamp)
        dedup_id (str): Unique identifier for the notification
        ttl_hours (int): Hours until the record expires (default: 2)
    
    Returns:
        bool: True if this is a duplicate, False if it's new
    """
    # If deduplication is disabled, always return False (not a duplicate)
    if not DEDUP_ENABLED:
        logger.debug("Deduplication disabled, allowing notification")
        return False
    
    try:
        # Check for existing record
        resp = table.get_item(Key={"job_run_id": partition_key, "dedup_id": dedup_id})
        if "Item" in resp:
            logger.info(f"Duplicate notification detected: {dedup_id}")
            return True  # Duplicate
        
        # Not a duplicate, write record
        expire_at = int(time.time()) + ttl_hours * 3600
        table.put_item(Item={
            "job_run_id": partition_key, 
            "dedup_id": dedup_id, 
            "expire_at": expire_at
        })
        logger.debug(f"Notification record written: {dedup_id}")
        return False
    except Exception as e:
        logger.error(f"Error in deduplication check: {e}")
        # On error, allow the notification to proceed (fail open)
        return False