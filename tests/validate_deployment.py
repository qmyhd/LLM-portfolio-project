#!/usr/bin/env python3
"""
Deployment Validation Script
===========================

Quick validation script to ensure the codebase is ready for deployment.
Checks all critical files, imports, and configurations.

Usage:
    python validate_deployment.py
"""

import os
import sys
import importlib.util
from pathlib import Path
from typing import List, Tuple, Dict, Any

# Add project root to Python path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# TOML parsing with fallback for different Python versions
try:
    # Python 3.11+
    import tomllib
except ImportError:
    try:
        # Python 3.8-3.10 fallback
        import tomli as tomllib
    except ImportError:
        tomllib = None


def load_pyproject(file_path: Path) -> Dict[Any, Any]:
    """
    Load and parse pyproject.toml file with proper error handling.

    Args:
        file_path: Path to the pyproject.toml file

    Returns:
        Dict containing parsed TOML data

    Raises:
        FileNotFoundError: If the file doesn't exist
        ValueError: If TOML parsing fails or tomllib is not available
    """
    if not file_path.exists():
        raise FileNotFoundError(f"TOML file not found: {file_path}")

    if tomllib is None:
        raise ValueError(
            "TOML parsing not available. Install 'tomli' package for Python < 3.11: "
            "pip install tomli"
        )

    try:
        with open(file_path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"Malformed TOML in {file_path}: {e}")
    except Exception as e:
        raise ValueError(f"Failed to read TOML file {file_path}: {e}")


def validate_toml_file(file_path: Path) -> Tuple[bool, str]:
    """
    Validate a TOML file can be parsed correctly.

    Args:
        file_path: Path to the TOML file

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        load_pyproject(file_path)
        return True, "Valid TOML syntax"
    except FileNotFoundError:
        return False, "File not found"
    except ValueError as e:
        return False, str(e)


def check_file_exists(file_path: Path) -> bool:
    """Check if a critical file exists."""
    return file_path.exists() and file_path.is_file()


def check_directory_exists(dir_path: Path) -> bool:
    """Check if a directory exists."""
    return dir_path.exists() and dir_path.is_dir()


def check_import(module_name: str) -> Tuple[bool, str]:
    """Check if a module can be imported."""
    try:
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            return False, f"Module {module_name} not found"
        return True, f"Module {module_name} available"
    except Exception as e:
        return False, f"Import error for {module_name}: {e}"


def validate_codebase() -> bool:
    """Run complete validation checks."""
    project_root = Path(
        __file__
    ).parent.parent  # Go up one more level since we're now in tests/
    success = True

    print("🔍 LLM Portfolio Project - Deployment Validation")
    print("=" * 50)

    # Critical files check
    critical_files = [
        "pyproject.toml",
        "requirements.txt",
        "generate_journal.py",
        ".gitignore",
        "src/__init__.py",
        "src/config.py",
        "src/data_collector.py",
        "src/journal_generator.py",
        "src/db.py",
    ]

    print("\n📁 Checking critical files...")
    for file_name in critical_files:
        file_path = project_root / file_name
        if check_file_exists(file_path):
            print(f"  ✅ {file_name}")
        else:
            print(f"  ❌ {file_name} - MISSING")
            success = False

    # Directory structure check
    required_dirs = [
        "src",
        "src/bot",
        "scripts",
        "data",
        "data/raw",
        "data/processed",
        "data/database",
    ]

    print("\n📂 Checking directory structure...")
    for dir_name in required_dirs:
        dir_path = project_root / dir_name
        if check_directory_exists(dir_path):
            print(f"  ✅ {dir_name}/")
        else:
            print(f"  ⚠️  {dir_name}/ - Will be created during setup")

    # Entry points validation - separate Python and TOML files
    python_entry_points = ["generate_journal.py", "src/bot/bot.py"]
    toml_files = ["pyproject.toml"]

    print("\n🚀 Checking Python entry points...")
    for entry_point in python_entry_points:
        file_path = project_root / entry_point
        if check_file_exists(file_path):
            # Quick syntax check for Python files
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                compile(content, str(file_path), "exec")
                print(f"  ✅ {entry_point} - Valid Python syntax")
            except SyntaxError as e:
                print(f"  ❌ {entry_point} - Python syntax error: {e}")
                success = False
            except Exception as e:
                print(f"  ⚠️  {entry_point} - Could not validate: {e}")
        else:
            print(f"  ❌ {entry_point} - MISSING")
            success = False

    print("\n📋 Checking TOML configuration files...")
    for toml_file in toml_files:
        file_path = project_root / toml_file
        if check_file_exists(file_path):
            is_valid, message = validate_toml_file(file_path)
            if is_valid:
                print(f"  ✅ {toml_file} - {message}")
            else:
                print(f"  ❌ {toml_file} - {message}")
                success = False
        else:
            print(f"  ❌ {toml_file} - MISSING")
            success = False

    # Core module availability (without importing)
    core_modules = [
        "src.config",
        "src.db",
        "src.data_collector",
        "src.journal_generator",
        "src.bot.bot",
    ]

    print("\n🐍 Checking core modules...")
    for module in core_modules:
        available, message = check_import(module)
        if available:
            print(f"  ✅ {message}")
        else:
            print(f"  ⚠️  {message}")

    # Configuration files
    config_files = [".env.example"]

    print("\n⚙️  Checking configuration...")
    for config_file in config_files:
        file_path = project_root / config_file
        if check_file_exists(file_path):
            print(f"  ✅ {config_file}")
        else:
            print(f"  ⚠️  {config_file} - Optional, will be created during setup")

    # Validate pyproject.toml metadata
    pyproject_path = project_root / "pyproject.toml"
    if check_file_exists(pyproject_path):
        try:
            pyproject_data = load_pyproject(pyproject_path)
            project_section = pyproject_data.get("project", {})
            if project_section:
                name = project_section.get("name", "Unknown")
                version = project_section.get("version", "Unknown")
                print(f"  ✅ pyproject.toml metadata - {name} v{version}")
            else:
                print("  ⚠️  pyproject.toml missing [project] section")
        except ValueError as e:
            print(f"  ❌ pyproject.toml validation failed: {e}")
            success = False

    # Git readiness
    print("\n📦 Checking git readiness...")

    gitignore_path = project_root / ".gitignore"
    if check_file_exists(gitignore_path):
        with open(gitignore_path, "r", encoding="utf-8-sig") as f:  # Handle BOM
            gitignore_content = f.read()

        # Check for essential ignore patterns
        gitignore_lines = [
            line.strip()
            for line in gitignore_content.splitlines()
            if line.strip() and not line.startswith("#")
        ]

        # Define what we're looking for and what matches it
        pattern_checks = {
            ".env": [".env", ".env*"],
            "__pycache__": ["__pycache__/", "__pycache__"],
            "*.pyc": ["*.py[cod]", "*.pyc", "*$py.class"],
            "data/": ["data/"],
        }

        missing_ignores = []
        for required_pattern, possible_matches in pattern_checks.items():
            found = False
            for line in gitignore_lines:
                if any(match in line for match in possible_matches):
                    found = True
                    break
            if not found:
                missing_ignores.append(required_pattern)

        if not missing_ignores:
            print("  ✅ .gitignore contains essential patterns")
        else:
            print(f"  ⚠️  .gitignore missing: {', '.join(missing_ignores)}")
    else:
        print("  ❌ .gitignore - MISSING")
        success = False

    # Requirements.txt validation
    print("\n📋 Checking dependencies...")
    req_file = project_root / "requirements.txt"
    if check_file_exists(req_file):
        with open(req_file, "r") as f:
            requirements = f.read()

        essential_deps = [
            "pandas",
            "yfinance",
            "python-dotenv",
            "pydantic-settings",
            "sqlalchemy",
            "discord.py",
        ]

        missing_deps = []
        for dep in essential_deps:
            if dep not in requirements:
                missing_deps.append(dep)

        if not missing_deps:
            print("  ✅ All essential dependencies present")
        else:
            print(f"  ⚠️  Missing dependencies: {', '.join(missing_deps)}")

        print(f"  📊 Total dependencies: {len(requirements.splitlines())}")
    else:
        print("  ❌ requirements.txt - MISSING")
        success = False

    # Final validation
    print("\n" + "=" * 50)
    if success:
        print("🎉 VALIDATION PASSED - Codebase is deployment ready!")
        print("\nNext steps:")
        print("1. git add . && git commit -m 'Prepare for deployment'")
        print("2. git push")
        print("3. On remote environment: pip install -e .")
        return True
    else:
        print("❌ VALIDATION FAILED - Please fix the issues above")
        return False


if __name__ == "__main__":
    success = validate_codebase()
    sys.exit(0 if success else 1)
