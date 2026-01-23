"""
Shared utilities for Lambda functions.

This module provides common functionality used across all Lambda handlers:
- AWS Secrets Manager integration
- Database connections (Supabase + RDS)
- Logging configuration
- Response helpers
"""

import json
import logging
import os
import sys
from typing import Any, Dict, Optional

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def configure_logging(level: str = "INFO") -> logging.Logger:
    """
    Configure Lambda-appropriate logging.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)

    Returns:
        Configured logger
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Lambda sets up root logger, we just configure format
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=True,
    )

    logger = logging.getLogger("lambda")
    logger.setLevel(log_level)
    return logger


def load_secrets() -> bool:
    """
    Load secrets from AWS Secrets Manager into environment.

    Returns:
        True if secrets loaded successfully, False otherwise
    """
    try:
        from src.aws_secrets import load_secrets_to_env, should_use_aws_secrets

        if should_use_aws_secrets():
            load_secrets_to_env()
            return True
        else:
            # Secrets already in environment (local dev or container)
            return True
    except Exception as e:
        logging.error(f"Failed to load secrets: {e}")
        return False


def success_response(
    message: str,
    data: Optional[Dict[str, Any]] = None,
    status_code: int = 200,
) -> Dict[str, Any]:
    """
    Create a standardized success response.

    Args:
        message: Success message
        data: Optional additional data
        status_code: HTTP status code

    Returns:
        Lambda response dict
    """
    body = {"status": "success", "message": message}
    if data:
        body["data"] = data

    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def error_response(
    message: str,
    error: Optional[str] = None,
    status_code: int = 500,
) -> Dict[str, Any]:
    """
    Create a standardized error response.

    Args:
        message: Error message
        error: Optional error details
        status_code: HTTP status code

    Returns:
        Lambda response dict
    """
    body = {"status": "error", "message": message}
    if error:
        body["error"] = error

    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def validate_db_connection(use_rds: bool = False) -> bool:
    """
    Validate database connection is available.

    Args:
        use_rds: If True, check RDS connection. Otherwise check Supabase.

    Returns:
        True if connection is healthy
    """
    try:
        from src.db import healthcheck, rds_healthcheck

        if use_rds:
            return rds_healthcheck()
        else:
            healthcheck()
            return True
    except Exception as e:
        logging.error(f"Database connection validation failed: {e}")
        return False
