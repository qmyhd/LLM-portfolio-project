#!/usr/bin/env python3
"""
Deploy Lambda functions using AWS SAM.

This script:
1. Builds the Lambda layer with dependencies
2. Packages the SAM template
3. Deploys the CloudFormation stack

Usage:
    python scripts/deploy_lambdas.py [--env production|staging|development]

Requirements:
    - AWS SAM CLI installed: https://docs.aws.amazon.com/serverless-application-model/
    - AWS credentials configured
    - Docker (for building Lambda layers)
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_command(cmd: list, cwd: Path = PROJECT_ROOT) -> int:
    """Run a command and return exit code."""
    print(f"\n{'='*60}")
    print(f"Running: {' '.join(cmd)}")
    print(f"{'='*60}\n")
    result = subprocess.run(cmd, cwd=cwd)
    return result.returncode


def build_dependencies_layer():
    """Build the Lambda dependencies layer."""
    layer_dir = PROJECT_ROOT / "layers" / "dependencies"
    python_dir = layer_dir / "python"

    # Clean and recreate
    if layer_dir.exists():
        shutil.rmtree(layer_dir)
    python_dir.mkdir(parents=True)

    # Create minimal requirements for Lambda
    lambda_requirements = [
        "boto3>=1.34",
        "botocore>=1.34",
        "sqlalchemy>=2.0",
        "psycopg2-binary>=2.9",
        "pydantic>=2.0",
        "pydantic-settings>=2.0",
        "python-dotenv>=1.0",
        "openai>=1.0",
        "snaptrade-python-sdk>=11.0",
        "textblob>=0.17",
        "pandas>=2.0",
    ]

    requirements_file = layer_dir / "requirements.txt"
    requirements_file.write_text("\n".join(lambda_requirements))

    # Install to python directory
    result = run_command(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(requirements_file),
            "-t",
            str(python_dir),
            "--platform",
            "manylinux2014_x86_64",
            "--only-binary=:all:",
        ]
    )

    if result != 0:
        print("Warning: Some packages may not have pre-built wheels")
        # Fallback without platform restriction
        run_command(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                str(requirements_file),
                "-t",
                str(python_dir),
            ]
        )

    return layer_dir


def validate_template():
    """Validate the SAM template."""
    return run_command(["sam", "validate", "--lint"])


def build_sam():
    """Build SAM application."""
    return run_command(
        [
            "sam",
            "build",
            "--use-container",  # Use Docker for consistent builds
            "--cached",  # Cache build artifacts
        ]
    )


def deploy_sam(env: str, guided: bool = False):
    """Deploy SAM application."""
    stack_name = f"llm-portfolio-lambdas-{env}"

    cmd = [
        "sam",
        "deploy",
        "--stack-name",
        stack_name,
        "--capabilities",
        "CAPABILITY_NAMED_IAM",
        "--no-fail-on-empty-changeset",
        "--parameter-overrides",
        f"Environment={env}",
    ]

    if guided:
        cmd.append("--guided")
    else:
        cmd.extend(
            [
                "--no-confirm-changeset",
                "--resolve-s3",  # Auto-create S3 bucket for artifacts
            ]
        )

    return run_command(cmd)


def main():
    parser = argparse.ArgumentParser(description="Deploy Lambda functions")
    parser.add_argument(
        "--env",
        choices=["production", "staging", "development"],
        default="development",
        help="Deployment environment",
    )
    parser.add_argument("--guided", action="store_true", help="Run guided deployment")
    parser.add_argument(
        "--skip-layer", action="store_true", help="Skip building dependencies layer"
    )
    parser.add_argument(
        "--validate-only", action="store_true", help="Only validate the template"
    )

    args = parser.parse_args()

    print(f"🚀 Deploying LLM Portfolio Lambda functions")
    print(f"   Environment: {args.env}")
    print(f"   Project root: {PROJECT_ROOT}")

    # Step 1: Validate template
    print("\n📋 Step 1: Validating SAM template...")
    if validate_template() != 0:
        print("❌ Template validation failed")
        return 1

    if args.validate_only:
        print("✅ Template validation passed")
        return 0

    # Step 2: Build dependencies layer
    if not args.skip_layer:
        print("\n📦 Step 2: Building dependencies layer...")
        build_dependencies_layer()

    # Step 3: Build SAM application
    print("\n🔨 Step 3: Building SAM application...")
    if build_sam() != 0:
        print("❌ SAM build failed")
        return 1

    # Step 4: Deploy
    print(f"\n🚀 Step 4: Deploying to {args.env}...")
    if deploy_sam(args.env, args.guided) != 0:
        print("❌ Deployment failed")
        return 1

    print("\n✅ Deployment completed successfully!")
    print(f"\nNext steps:")
    print(f"  1. Verify functions in AWS Lambda console")
    print(f"  2. Check EventBridge rules are enabled")
    print(f"  3. Monitor CloudWatch logs for execution")

    return 0


if __name__ == "__main__":
    sys.exit(main())
