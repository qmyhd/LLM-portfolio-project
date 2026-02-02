#!/usr/bin/env python3
"""
AWS Secrets Manager Validation Script

Validates that secrets can be loaded from AWS Secrets Manager and reports
which required keys are present or missing.

Usage:
    python scripts/check_secrets.py

Environment Variables:
    USE_AWS_SECRETS: Set to "1" to enable (auto-set on EC2)
    AWS_SECRET_NAME: Secret name (default: "qqqAppsecrets")
    AWS_REGION: AWS region (default: "us-east-1")

Exit Codes:
    0: All required secrets present
    1: Missing required secrets or connection error
"""

import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    """Validate AWS Secrets Manager configuration and required keys."""
    print("=" * 60)
    print("AWS Secrets Manager Validation")
    print("=" * 60)

    # Check for /etc/llm-portfolio/llm.env first
    env_file = Path("/etc/llm-portfolio/llm.env")
    if env_file.exists():
        print(f"\n✅ Found central env file: {env_file}")
        # Load it
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())
    else:
        print(f"\n⚠️  Central env file not found: {env_file}")
        print("   Create it with: sudo mkdir -p /etc/llm-portfolio")
        print("   Then: sudo tee /etc/llm-portfolio/llm.env << 'EOF'")
        print("   USE_AWS_SECRETS=1")
        print("   AWS_REGION=us-east-1")
        print("   AWS_SECRET_NAME=qqqAppsecrets")
        print("   EOF")

    # Environment configuration
    use_aws = os.environ.get("USE_AWS_SECRETS", "0")
    region = os.environ.get("AWS_REGION", "us-east-1")
    secret_name = os.environ.get("AWS_SECRET_NAME", "")
    prefix = os.environ.get("AWS_SECRETS_PREFIX", "llm-portfolio")
    env = os.environ.get("AWS_SECRETS_ENV", "production")

    # Resolve secret name
    if secret_name:
        resolved_name = secret_name
        resolution_method = "AWS_SECRET_NAME (preferred)"
    else:
        resolved_name = f"{prefix}/{env}"
        resolution_method = f"{{AWS_SECRETS_PREFIX}}/{{AWS_SECRETS_ENV}} (fallback)"

    print("\nConfiguration:")
    print(f"  USE_AWS_SECRETS: {use_aws}")
    print(f"  AWS_REGION: {region}")
    print(f"  Resolved Secret: {resolved_name}")
    print(f"  Resolution Method: {resolution_method}")

    if use_aws != "1":
        print("\n⚠️  AWS Secrets Manager is DISABLED")
        print("   Set USE_AWS_SECRETS=1 to enable")
        return 0

    # Try to load secrets
    print("\n" + "-" * 60)
    print("Loading secrets from AWS Secrets Manager...")
    print("-" * 60)

    try:
        # Force AWS secrets mode
        os.environ["USE_AWS_SECRETS"] = "1"
        os.environ["AWS_SECRET_NAME"] = resolved_name
        os.environ["AWS_REGION"] = region

        from src.aws_secrets import load_secrets_to_env, SECRET_KEY_MAPPING

        count = load_secrets_to_env(secret_name=resolved_name)
        print(f"\n✅ Loaded {count} secrets successfully")

    except Exception as e:
        print(f"\n❌ Failed to load secrets: {e}")
        print("\nPossible causes:")
        print(
            "  1. EC2 instance role doesn't have secretsmanager:GetSecretValue permission"
        )
        print("  2. Secret name doesn't exist in AWS Secrets Manager")
        print("  3. AWS region mismatch")
        print("\nTo debug:")
        print("  aws secretsmanager describe-secret --secret-id " + resolved_name)
        return 1

    # Check required keys
    print("\n" + "-" * 60)
    print("Checking Required Keys:")
    print("-" * 60)

    required_keys = [
        "DATABASE_URL",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "OPENAI_API_KEY",
        "DISCORD_BOT_TOKEN",
        "API_SECRET_KEY",
    ]

    recommended_keys = [
        "SNAPTRADE_CLIENT_ID",
        "SNAPTRADE_CONSUMER_KEY",
        "SNAPTRADE_CLIENT_SECRET",
        "SNAPTRADE_USER_ID",
        "SNAPTRADE_USER_SECRET",
        "DATABENTO_API_KEY",
        "LOG_CHANNEL_IDS",
    ]

    missing_required = []
    missing_recommended = []

    print("\nRequired keys:")
    for key in required_keys:
        value = os.environ.get(key)
        if value:
            masked = value[:8] + "..." if len(value) > 12 else "***"
            print(f"  ✅ {key}: {masked}")
        else:
            print(f"  ❌ {key}: MISSING")
            missing_required.append(key)

    print("\nRecommended keys:")
    for key in recommended_keys:
        value = os.environ.get(key)
        if value:
            masked = value[:8] + "..." if len(value) > 12 else "***"
            print(f"  ✅ {key}: {masked}")
        else:
            print(f"  ⚠️  {key}: not set")
            missing_recommended.append(key)

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    if missing_required:
        print(f"\n❌ Missing {len(missing_required)} REQUIRED keys:")
        for key in missing_required:
            print(f"   - {key}")
        print("\nThe application will NOT work without these keys!")
        return 1

    if missing_recommended:
        print(f"\n⚠️  Missing {len(missing_recommended)} recommended keys:")
        for key in missing_recommended:
            print(f"   - {key}")
        print("\nSome features may be unavailable.")

    print("\n✅ All required secrets are configured correctly!")
    # Avoid logging the full secret name, which may be derived from sensitive env vars
    masked_secret = "[redacted]" if not resolved_name else f"[redacted:{len(resolved_name)}]"
    print(f"   Secret: {masked_secret}")
    print(f"   Region: {region}")
    print(f"   Total keys loaded: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
