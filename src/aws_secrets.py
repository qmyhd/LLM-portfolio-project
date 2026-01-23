"""
AWS Secrets Manager Integration

Fetches secrets from AWS Secrets Manager and loads them as environment variables.
Used on EC2 instances instead of .env files for better security.

Usage:
    # At application startup (before importing other modules)
    from src.aws_secrets import load_secrets_to_env
    load_secrets_to_env()

    # Or use as a context manager
    with secrets_env():
        # Your application code here
        pass

Required IAM permissions:
    {
        "Effect": "Allow",
        "Action": [
            "secretsmanager:GetSecretValue"
        ],
        "Resource": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:llm-portfolio/*"
    }

Environment Variables:
    AWS_SECRETS_PREFIX: Secret name prefix (default: "llm-portfolio")
    AWS_REGION: AWS region (default: "us-east-1")
    USE_AWS_SECRETS: Set to "1" to enable (auto-detected on EC2)
"""

import json
import logging
import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Secret name mapping: environment variable -> secret key in Secrets Manager
# These are the keys expected in the AWS Secrets Manager secret
SECRET_KEY_MAPPING = {
    # Database - Supabase (primary)
    "DATABASE_URL": "DATABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY": "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_URL": "SUPABASE_URL",
    "SUPABASE_KEY": "SUPABASE_KEY",
    # Database - RDS (for OHLCV and high-volume writes)
    # NOTE: RDS secrets may be in a separate secret (see AWS_RDS_SECRET_NAME)
    "RDS_HOST": "RDS_HOST",
    "RDS_PORT": "RDS_PORT",
    "RDS_DATABASE": "RDS_DATABASE",
    "RDS_USER": "RDS_USER",
    "RDS_PASSWORD": "RDS_PASSWORD",
    # OpenAI (required for NLP)
    "OPENAI_API_KEY": "OPENAI_API_KEY",
    # Discord Bot
    "DISCORD_BOT_TOKEN": "DISCORD_BOT_TOKEN",
    "LOG_CHANNEL_IDS": "LOG_CHANNEL_IDS",
    # SnapTrade (optional)
    "SNAPTRADE_CLIENT_ID": "SNAPTRADE_CLIENT_ID",
    "SNAPTRADE_CONSUMER_KEY": "SNAPTRADE_CONSUMER_KEY",
    "SNAPTRADE_USER_ID": "SNAPTRADE_USER_ID",
    "SNAPTRADE_USER_SECRET": "SNAPTRADE_USER_SECRET",
    # Twitter (optional)
    "TWITTER_BEARER_TOKEN": "TWITTER_BEARER_TOKEN",
    # Databento (optional)
    "DATABENTO_API_KEY": "DATABENTO_API_KEY",
    # S3 (optional - for Parquet archive)
    "S3_BUCKET_NAME": "S3_BUCKET_NAME",
    "S3_RAW_DAILY_PREFIX": "S3_RAW_DAILY_PREFIX",
}

# RDS-specific secret keys (for separate RDS secret)
RDS_SECRET_KEY_MAPPING = {
    "RDS_HOST": ["host", "RDS_HOST", "hostname"],
    "RDS_PORT": ["port", "RDS_PORT"],
    "RDS_DATABASE": ["dbname", "database", "RDS_DATABASE", "dbInstanceIdentifier"],
    "RDS_USER": ["username", "RDS_USER", "user"],
    "RDS_PASSWORD": ["password", "RDS_PASSWORD"],
}


def is_ec2_instance() -> bool:
    """
    Check if running on an EC2 instance by looking for instance metadata.

    Returns:
        True if running on EC2, False otherwise
    """
    # Check for EC2 metadata service token
    if os.path.exists("/sys/hypervisor/uuid"):
        try:
            with open("/sys/hypervisor/uuid") as f:
                uuid = f.read().strip().lower()
                if uuid.startswith("ec2"):
                    return True
        except Exception:
            pass

    # Check for IMDSv2 token endpoint (more reliable)
    try:
        import urllib.request

        req = urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/instance-id",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=1) as response:
            return response.status == 200
    except Exception:
        pass

    return False


def should_use_aws_secrets() -> bool:
    """
    Determine if AWS Secrets Manager should be used.

    Priority:
    1. USE_AWS_SECRETS environment variable
    2. Auto-detect EC2 instance
    """
    env_setting = os.environ.get("USE_AWS_SECRETS", "").lower()
    if env_setting in ("1", "true", "yes"):
        return True
    if env_setting in ("0", "false", "no"):
        return False

    # Auto-detect EC2
    return is_ec2_instance()


@lru_cache(maxsize=1)
def get_secrets_client():
    """
    Get boto3 Secrets Manager client.

    Returns:
        boto3 SecretsManager client

    Raises:
        ImportError: If boto3 is not installed
    """
    try:
        import boto3
    except ImportError:
        raise ImportError(
            "boto3 is required for AWS Secrets Manager. "
            "Install with: pip install boto3"
        )

    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client("secretsmanager", region_name=region)


def fetch_secret(secret_name: str) -> Dict[str, str]:
    """
    Fetch a secret from AWS Secrets Manager.

    Args:
        secret_name: The name of the secret in AWS Secrets Manager

    Returns:
        Dict of secret key-value pairs

    Raises:
        Exception: If secret cannot be fetched
    """
    client = get_secrets_client()

    try:
        response = client.get_secret_value(SecretId=secret_name)
    except client.exceptions.ResourceNotFoundException:
        logger.error(f"Secret not found: {secret_name}")
        raise
    except client.exceptions.AccessDeniedException:
        logger.error(f"Access denied to secret: {secret_name}")
        raise
    except Exception as e:
        logger.error(f"Error fetching secret {secret_name}: {e}")
        raise

    # Parse secret value (JSON format expected)
    secret_value = response.get("SecretString")
    if not secret_value:
        logger.warning(f"Secret {secret_name} has no string value")
        return {}

    try:
        return json.loads(secret_value)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse secret {secret_name} as JSON: {e}")
        raise


def load_secrets_to_env(
    secret_name: Optional[str] = None,
    overwrite: bool = False,
) -> int:
    """
    Load secrets from AWS Secrets Manager into environment variables.

    Args:
        secret_name: Name of the secret in AWS Secrets Manager.
                     Defaults to "llm-portfolio/production"
        overwrite: If True, overwrite existing environment variables

    Returns:
        Number of environment variables set

    Example:
        # At application startup
        from src.aws_secrets import load_secrets_to_env

        if os.environ.get("USE_AWS_SECRETS") == "1":
            count = load_secrets_to_env()
            print(f"Loaded {count} secrets from AWS Secrets Manager")
    """
    if not should_use_aws_secrets():
        logger.debug("AWS Secrets Manager not enabled, skipping")
        return 0

    if secret_name is None:
        # Check for direct secret name first (preferred)
        secret_name = os.environ.get("AWS_SECRET_NAME")
        if not secret_name:
            # Fall back to prefix/env pattern
            prefix = os.environ.get("AWS_SECRETS_PREFIX", "llm-portfolio")
            env = os.environ.get("AWS_SECRETS_ENV", "production")
            secret_name = f"{prefix}/{env}"

    logger.info(f"Loading secrets from AWS Secrets Manager: {secret_name}")

    try:
        secrets = fetch_secret(secret_name)
    except Exception as e:
        logger.error(f"Failed to load secrets: {e}")
        return 0

    count = 0
    for env_var, secret_key in SECRET_KEY_MAPPING.items():
        if secret_key in secrets:
            value = secrets[secret_key]
            if value is not None:
                # Only set if not already present or overwrite is True
                if overwrite or env_var not in os.environ:
                    os.environ[env_var] = str(value)
                    count += 1
                    logger.debug(f"Set {env_var} from secret")

    logger.info(f"Loaded {count} environment variables from AWS Secrets Manager")

    # Also load RDS secrets if configured separately
    rds_count = load_rds_secrets_to_env(overwrite=overwrite)

    return count + rds_count


def load_rds_secrets_to_env(
    rds_secret_name: Optional[str] = None,
    overwrite: bool = False,
) -> int:
    """
    Load RDS secrets from a separate AWS Secrets Manager secret.

    This handles the case where RDS credentials are stored in a separate
    secret (e.g., created by RDS or manually for OHLCV data).

    Args:
        rds_secret_name: Name of the RDS secret. Defaults to AWS_RDS_SECRET_NAME env var.
        overwrite: If True, overwrite existing environment variables

    Returns:
        Number of environment variables set

    Environment Variables:
        AWS_RDS_SECRET_NAME: Name of the RDS secret (e.g., "RDS/ohlcvdata")
    """
    if rds_secret_name is None:
        rds_secret_name = os.environ.get("AWS_RDS_SECRET_NAME")

    if not rds_secret_name:
        logger.debug("No RDS secret name configured, skipping RDS secrets")
        return 0

    logger.info(f"Loading RDS secrets from: {rds_secret_name}")

    try:
        secrets = fetch_secret(rds_secret_name)
    except Exception as e:
        logger.warning(f"Failed to load RDS secrets from {rds_secret_name}: {e}")
        return 0

    count = 0
    for env_var, possible_keys in RDS_SECRET_KEY_MAPPING.items():
        # Try each possible key name for this env var
        for key in possible_keys:
            if key in secrets:
                value = secrets[key]
                if value is not None:
                    if overwrite or env_var not in os.environ:
                        os.environ[env_var] = str(value)
                        count += 1
                        logger.debug(f"Set {env_var} from RDS secret (key: {key})")
                    break  # Found a value, stop looking

    logger.info(f"Loaded {count} RDS environment variables")
    return count


@contextmanager
def secrets_env(secret_name: Optional[str] = None):
    """
    Context manager to temporarily load secrets into environment.

    Args:
        secret_name: Name of the secret in AWS Secrets Manager

    Example:
        with secrets_env():
            from src.config import settings
            config = settings()
    """
    # Store original environment
    original_env = dict(os.environ)

    try:
        load_secrets_to_env(secret_name)
        yield
    finally:
        # Restore original environment
        os.environ.clear()
        os.environ.update(original_env)


def create_secret_template() -> dict:
    """
    Generate a template for the AWS Secrets Manager secret.

    Returns:
        Dict template with placeholder values

    Usage:
        import json
        from src.aws_secrets import create_secret_template

        template = create_secret_template()
        print(json.dumps(template, indent=2))

        # Then create in AWS:
        # aws secretsmanager create-secret --name llm-portfolio/production --secret-string '...'
    """
    return {
        # Required - Supabase
        "DATABASE_URL": "postgresql://postgres.[project]:[service-role-key]@[region].pooler.supabase.com:6543/postgres",
        "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_your_key",
        # Required - OpenAI
        "OPENAI_API_KEY": "sk-your_openai_key",
        # Required - Discord
        "DISCORD_BOT_TOKEN": "your_discord_bot_token",
        "LOG_CHANNEL_IDS": "channel_id1,channel_id2",
        # Optional - SnapTrade
        "SNAPTRADE_CLIENT_ID": "",
        "SNAPTRADE_CONSUMER_KEY": "",
        "SNAPTRADE_USER_ID": "",
        "SNAPTRADE_USER_SECRET": "",
        # Optional - Twitter
        "TWITTER_BEARER_TOKEN": "",
        # Optional - Databento
        "DATABENTO_API_KEY": "",
        # Optional - RDS (for OHLCV and high-volume operations)
        "RDS_HOST": "your-db.region.rds.amazonaws.com",
        "RDS_PORT": "5432",
        "RDS_DATABASE": "postgres",
        "RDS_USER": "postgres",
        "RDS_PASSWORD": "your_rds_password",
        # Optional - S3
        "S3_BUCKET_NAME": "",
        "S3_RAW_DAILY_PREFIX": "ohlcv/daily/",
    }


def build_rds_connection_url(
    host: Optional[str] = None,
    port: Optional[str] = None,
    database: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    ssl_mode: str = "require",
) -> Optional[str]:
    """
    Build a PostgreSQL connection URL from RDS components.

    Args:
        host: RDS hostname (defaults to RDS_HOST env var)
        port: RDS port (defaults to RDS_PORT env var, fallback 5432)
        database: Database name (defaults to RDS_DATABASE env var)
        user: Username (defaults to RDS_USER env var)
        password: Password (defaults to RDS_PASSWORD env var)
        ssl_mode: SSL mode (default: require)

    Returns:
        PostgreSQL connection URL or None if required fields missing

    Example:
        from src.aws_secrets import build_rds_connection_url

        # Uses environment variables
        rds_url = build_rds_connection_url()

        # Or with explicit values
        rds_url = build_rds_connection_url(
            host="my-db.rds.amazonaws.com",
            user="admin",
            password="secret123",
            database="mydb"
        )
    """
    # Get values from environment if not provided
    host = host or os.environ.get("RDS_HOST")
    port = port or os.environ.get("RDS_PORT", "5432")
    database = database or os.environ.get("RDS_DATABASE", "postgres")
    user = user or os.environ.get("RDS_USER")
    password = password or os.environ.get("RDS_PASSWORD")

    # Validate required fields
    if not all([host, user, password]):
        missing = []
        if not host:
            missing.append("RDS_HOST")
        if not user:
            missing.append("RDS_USER")
        if not password:
            missing.append("RDS_PASSWORD")
        logger.debug(f"Cannot build RDS URL - missing: {missing}")
        return None

    # URL-encode password for special characters
    from urllib.parse import quote_plus

    encoded_password = quote_plus(password)

    # Build connection URL with SSL
    url = f"postgresql://{user}:{encoded_password}@{host}:{port}/{database}"
    if ssl_mode:
        url += f"?sslmode={ssl_mode}"

    logger.debug(f"Built RDS connection URL for host: {host}")
    return url


def get_rds_connection_url() -> Optional[str]:
    """
    Get RDS connection URL, loading from Secrets Manager if needed.

    Returns:
        PostgreSQL connection URL for RDS, or None if not configured

    Example:
        from src.aws_secrets import get_rds_connection_url

        rds_url = get_rds_connection_url()
        if rds_url:
            engine = create_engine(rds_url)
    """
    # First try to build from environment (may already be loaded)
    url = build_rds_connection_url()
    if url:
        return url

    # Try loading secrets if not already loaded
    if should_use_aws_secrets():
        load_secrets_to_env()
        return build_rds_connection_url()

    return None


if __name__ == "__main__":
    # CLI tool for testing
    import argparse

    parser = argparse.ArgumentParser(description="AWS Secrets Manager helper")
    parser.add_argument(
        "--template",
        action="store_true",
        help="Print secret template JSON",
    )
    parser.add_argument(
        "--load",
        action="store_true",
        help="Load secrets and print count",
    )
    parser.add_argument(
        "--secret-name",
        default=None,
        help="Secret name in AWS Secrets Manager",
    )
    args = parser.parse_args()

    if args.template:
        template = create_secret_template()
        print(json.dumps(template, indent=2))
    elif args.load:
        os.environ["USE_AWS_SECRETS"] = "1"  # Force enable
        count = load_secrets_to_env(args.secret_name)
        print(f"Loaded {count} secrets")
    else:
        parser.print_help()
