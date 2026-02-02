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
        "Resource": "arn:aws:secretsmanager:us-east-1:298921514475:secret:qqqAppsecrets-FeRqIW"
    }

Environment Variables (in /etc/llm-portfolio/llm.env):
    AWS_SECRET_NAME: Preferred - direct secret name (e.g., "qqqAppsecrets")
    AWS_SECRETS_PREFIX: Fallback prefix if AWS_SECRET_NAME not set (default: "llm-portfolio")
    AWS_SECRETS_ENV: Fallback environment suffix (default: "production")
    AWS_REGION: AWS region (default: "us-east-1")
    USE_AWS_SECRETS: Set to "1" to enable (auto-detected on EC2)

Secret Resolution Order:
    1. AWS_SECRET_NAME (preferred) -> "qqqAppsecrets"
    2. {AWS_SECRETS_PREFIX}/{AWS_SECRETS_ENV} (fallback) -> "llm-portfolio/production"
"""

import json
import logging
import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Dict, Optional
import hashlib

logger = logging.getLogger(__name__)


def _redact_secret_name(secret_name: Optional[str]) -> str:
    # Return a *highly* redacted representation of a secret name for safe logging.
    # The returned value never includes any substring of the actual secret
    # identifier. It only exposes coarse metadata (such as length and
    # whether the name appears to be a direct name or a prefix/env form)
    # to aid debugging without leaking sensitive information.
    # Do not include any portion of the real secret name in logs.
    name_str = str(secret_name)
    length = len(name_str)
    # Heuristic: names containing "/" are typically prefix/env-style.
    kind = "prefix/env-style" if "/" in name_str else "direct-name"
    return f"<redacted-{kind}-secret-name len={length}>"


def _redact_template_for_output(template: Dict) -> Dict:
    """
    Return a deeply redacted version of a secret template for safe display.

    This preserves the overall structure and keys but replaces all leaf values
    with a constant placeholder so that no potentially sensitive example
    values are written to stdout or logs.
    """
    REDACTED_VALUE = "***redacted***"

    def _redact_value(value):
        if isinstance(value, dict):
            return {k: _redact_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_redact_value(v) for v in value]
        # For any leaf value type (str, int, bool, etc.), replace with placeholder.
        return REDACTED_VALUE

    return _redact_value(template)


# Secret name mapping: environment variable -> secret key in Secrets Manager
# These are the keys expected in the AWS Secrets Manager secret
SECRET_KEY_MAPPING = {
    # API Authentication
    "API_SECRET_KEY": "API_SECRET_KEY",  # For FastAPI bearer token auth
    # Database - Supabase (primary and only)
    "DATABASE_URL": "DATABASE_URL",
    "DATABASE_DIRECT_URL": "DATABASE_DIRECT_URL",
    "SUPABASE_SERVICE_ROLE_KEY": "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_URL": "SUPABASE_URL",
    "SUPABASE_ANON_KEY": "SUPABASE_ANON_KEY",
    "SUPABASE_SESSION_POOLER": "SUPABASE_SESSION_POOLER",
    # JWT
    "JWT_PUBLIC_KEY": "JWT_PUBLIC_KEY",
    "JWT_SECRET": "JWT_SECRET",
    # OpenAI (required for NLP)
    "OPENAI_API_KEY": "OPENAI_API_KEY",
    "OPENAI_MODEL_TRIAGE": "OPENAI_MODEL_TRIAGE",
    "OPENAI_MODEL_MAIN": "OPENAI_MODEL_MAIN",
    "OPENAI_MODEL_ESCALATION": "OPENAI_MODEL_ESCALATION",
    "OPENAI_MODEL_LONG": "OPENAI_MODEL_LONG",
    "OPENAI_MODEL_SUMMARY": "OPENAI_MODEL_SUMMARY",
    "OPENAI_MAX_OUTPUT_TOKENS": "OPENAI_MAX_OUTPUT_TOKENS",
    "OPENAI_REASONING_EFFORT_MAIN": "OPENAI_REASONING_EFFORT_MAIN",
    "OPENAI_PROMPT_VERSION": "OPENAI_PROMPT_VERSION",
    "OPENAI_PROMPT_CACHE_KEY": "OPENAI_PROMPT_CACHE_KEY",
    "OPENAI_PROMPT_CACHE_RETENTION": "OPENAI_PROMPT_CACHE_RETENTION",
    "OPENAI_LONG_CONTEXT_THRESHOLD_TOKENS": "OPENAI_LONG_CONTEXT_THRESHOLD_TOKENS",
    "OPENAI_LONG_CONTEXT_THRESHOLD_CHARS": "OPENAI_LONG_CONTEXT_THRESHOLD_CHARS",
    "OPENAI_ESCALATION_THRESHOLD": "OPENAI_ESCALATION_THRESHOLD",
    # Discord Bot
    "DISCORD_BOT_TOKEN": "DISCORD_BOT_TOKEN",
    "DISCORD_CLIENT_ID": "DISCORD_CLIENT_ID",
    "DISCORD_CLIENT_SECRET": "DISCORD_CLIENT_SECRET",
    "LOG_CHANNEL_IDS": "LOG_CHANNEL_IDS",
    # SnapTrade
    "SNAPTRADE_CLIENT_ID": "SNAPTRADE_CLIENT_ID",
    "SNAPTRADE_CONSUMER_KEY": "SNAPTRADE_CONSUMER_KEY",
    "SNAPTRADE_CLIENT_SECRET": "SNAPTRADE_CLIENT_SECRET",
    "SNAPTRADE_USER_ID": "SNAPTRADE_USER_ID",
    "SNAPTRADE_USER_SECRET": "SNAPTRADE_USER_SECRET",
    "SNAPTRADE_BROKER": "SNAPTRADE_BROKER",
    # Robinhood
    "ROBINHOOD_ACCOUNT_ID": "ROBINHOOD_ACCOUNT_ID",
    "ROBINHOOD_USERNAME": "ROBINHOOD_USERNAME",
    # Databento
    "DATABENTO_API_KEY": "DATABENTO_API_KEY",
    "DATABENTO_USER_ID": "DATABENTO_USER_ID",
    # Google OAuth
    "GOOGLE_CLIENT_ID": "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET": "GOOGLE_CLIENT_SECRET",
    # External APIs
    "LOGO_DEV_API_KEY": "LOGO_DEV_API_KEY",
    "LOGO_DEV_API_SECRET": "LOGO_DEV_API_SECRET",
    "LOGO_KIT_API_KEY": "LOGO_KIT_API_KEY",
    "FINHUB_API_KEY": "FINHUB_API_KEY",
    # GitHub
    "GITHUB_PERSONAL_ACCESS_TOKEN": "Github_Personal_Access_Token",
    # Twitter (optional)
    "TWITTER_BEARER_TOKEN": "TWITTER_BEARER_TOKEN",
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
        logger.error("Secret not found: %s", _redact_secret_name(secret_name))
        raise
    except client.exceptions.AccessDeniedException:
        logger.error(
            "Access denied when fetching secret: %s",
            _redact_secret_name(secret_name),
        )
        raise
    except Exception as e:
        logger.error(
            "Error fetching secret: %s",
            _redact_secret_name(secret_name),
        )
        raise

    # Parse secret value (JSON format expected)
    secret_value = response.get("SecretString")
    if not secret_value:
        logger.warning(
            "Secret has no string value: %s",
            _redact_secret_name(secret_name),
        )
        return {}

    try:
        return json.loads(secret_value)
    except json.JSONDecodeError as e:
        logger.error(
            "Failed to parse secret as JSON: %s (%s)",
            _redact_secret_name(secret_name),
            e,
        )
        raise


def load_secrets_to_env(
    secret_name: Optional[str] = None,
    overwrite: bool = False,
) -> int:
    """
    Load secrets from AWS Secrets Manager into environment variables.

    Args:
        secret_name: Name of the secret in AWS Secrets Manager.
                     Resolution order:
                     1. Explicit argument passed to this function
                     2. AWS_SECRET_NAME env var (preferred: "qqqAppsecrets")
                     3. {AWS_SECRETS_PREFIX}/{AWS_SECRETS_ENV} fallback
        overwrite: If True, overwrite existing environment variables

    Returns:
        Number of environment variables set

    Example:
        # At application startup (set AWS_SECRET_NAME=qqqAppsecrets in /etc/llm-portfolio/llm.env)
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

    logger.info(
        "Loading secrets from AWS Secrets Manager: %s",
        _redact_secret_name(secret_name),
    )

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
                    logger.debug("Set environment variable from AWS secret")

    logger.info(f"Loaded {count} environment variables from AWS Secrets Manager")

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

        # Then create/update in AWS:
        # aws secretsmanager create-secret --name qqqAppsecrets --secret-string '$(cat template.json)'
        # aws secretsmanager update-secret --secret-id qqqAppsecrets --secret-string '$(cat template.json)'
    """
    return {
        # Required - API Authentication
        "API_SECRET_KEY": "your_api_secret_key_for_fastapi",
        # Required - Supabase
        "DATABASE_URL": "postgresql://postgres.[project]:[service-role-key]@[region].pooler.supabase.com:6543/postgres",
        "DATABASE_DIRECT_URL": "postgresql://postgres:[password]@db.[project].supabase.co:5432/postgres",
        "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_your_key",
        "SUPABASE_URL": "https://[project].supabase.co",
        "SUPABASE_ANON_KEY": "your_supabase_anon_key",
        "SUPABASE_SESSION_POOLER": "postgresql://postgres.[project]:[password]@[region].pooler.supabase.com:5432/postgres",
        # JWT
        "JWT_PUBLIC_KEY": "",
        "JWT_SECRET": "",
        # Required - OpenAI
        "OPENAI_API_KEY": "sk-your_openai_key",
        "OPENAI_MODEL_TRIAGE": "gpt-5-mini",
        "OPENAI_MODEL_MAIN": "gpt-5-mini",
        "OPENAI_MODEL_ESCALATION": "gpt-5.1",
        "OPENAI_MODEL_LONG": "gpt-5.1",
        "OPENAI_MODEL_SUMMARY": "gpt-5-mini",
        "OPENAI_MAX_OUTPUT_TOKENS": "3500",
        "OPENAI_REASONING_EFFORT_MAIN": "medium",
        "OPENAI_PROMPT_VERSION": "v1.0",
        "OPENAI_PROMPT_CACHE_KEY": "discord_parser_v1",
        "OPENAI_PROMPT_CACHE_RETENTION": "24h",
        "OPENAI_LONG_CONTEXT_THRESHOLD_TOKENS": "500",
        "OPENAI_LONG_CONTEXT_THRESHOLD_CHARS": "2000",
        "OPENAI_ESCALATION_THRESHOLD": "0.84",
        # Required - Discord
        "DISCORD_BOT_TOKEN": "your_discord_bot_token",
        "DISCORD_CLIENT_ID": "",
        "DISCORD_CLIENT_SECRET": "",
        "LOG_CHANNEL_IDS": "channel_id1,channel_id2",
        # SnapTrade
        "SNAPTRADE_CLIENT_ID": "",
        "SNAPTRADE_CONSUMER_KEY": "",
        "SNAPTRADE_CLIENT_SECRET": "",
        "SNAPTRADE_USER_ID": "",
        "SNAPTRADE_USER_SECRET": "",
        "SNAPTRADE_BROKER": "ROBINHOOD",
        # Robinhood
        "ROBINHOOD_ACCOUNT_ID": "",
        "ROBINHOOD_USERNAME": "",
        # Databento
        "DATABENTO_API_KEY": "",
        "DATABENTO_USER_ID": "",
        # Google OAuth
        "GOOGLE_CLIENT_ID": "",
        "GOOGLE_CLIENT_SECRET": "",
        # External APIs
        "LOGO_DEV_API_KEY": "",
        "LOGO_DEV_API_SECRET": "",
        "LOGO_KIT_API_KEY": "",
        "FINHUB_API_KEY": "",
        # GitHub
        "Github_Personal_Access_Token": "",
        # Optional - Twitter
        "TWITTER_BEARER_TOKEN": "",
    }


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
        safe_template = _redact_template_for_output(template)
        print(json.dumps(safe_template, indent=2))
    elif args.load:
        os.environ["USE_AWS_SECRETS"] = "1"  # Force enable
        count = load_secrets_to_env(args.secret_name)
        print(f"Loaded {count} secrets")
    else:
        parser.print_help()
