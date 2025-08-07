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
from typing import List, Tuple

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
    project_root = Path(__file__).parent
    success = True
    
    print("🔍 LLM Portfolio Project - Deployment Validation")
    print("=" * 50)
    
    # Critical files check
    critical_files = [
        "setup.py",
        "requirements.txt", 
        "generate_journal.py",
        ".gitignore",
        "src/__init__.py",
        "src/config.py",
        "src/data_collector.py",
        "src/journal_generator.py",
        "src/database.py",
        "src/db.py"
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
        "data/database"
    ]
    
    print("\n📂 Checking directory structure...")
    for dir_name in required_dirs:
        dir_path = project_root / dir_name
        if check_directory_exists(dir_path):
            print(f"  ✅ {dir_name}/")
        else:
            print(f"  ⚠️  {dir_name}/ - Will be created during setup")
    
    # Entry points validation
    entry_points = [
        "generate_journal.py",
        "setup.py",
        "src/bot/bot.py"
    ]
    
    print("\n🚀 Checking entry points...")
    for entry_point in entry_points:
        file_path = project_root / entry_point
        if check_file_exists(file_path):
            # Quick syntax check
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                compile(content, str(file_path), 'exec')
                print(f"  ✅ {entry_point} - Valid Python syntax")
            except SyntaxError as e:
                print(f"  ❌ {entry_point} - Syntax error: {e}")
                success = False
            except Exception as e:
                print(f"  ⚠️  {entry_point} - Could not validate: {e}")
        else:
            print(f"  ❌ {entry_point} - MISSING")
            success = False
    
    # Core module availability (without importing)
    core_modules = [
        "src.config",
        "src.database", 
        "src.data_collector",
        "src.journal_generator",
        "src.bot.bot"
    ]
    
    print("\n🐍 Checking core modules...")
    for module in core_modules:
        available, message = check_import(module)
        if available:
            print(f"  ✅ {message}")
        else:
            print(f"  ⚠️  {message}")
    
    # Configuration files
    config_files = [
        ".env.example",
        "pyproject.toml"
    ]
    
    print("\n⚙️  Checking configuration...")
    for config_file in config_files:
        file_path = project_root / config_file
        if check_file_exists(file_path):
            print(f"  ✅ {config_file}")
        else:
            print(f"  ⚠️  {config_file} - Optional, will be created during setup")
    
    # Git readiness
    print("\n📦 Checking git readiness...")
    
    gitignore_path = project_root / ".gitignore"
    if check_file_exists(gitignore_path):
        with open(gitignore_path, 'r', encoding='utf-8-sig') as f:  # Handle BOM
            gitignore_content = f.read()
        
        # Check for essential ignore patterns
        gitignore_lines = [line.strip() for line in gitignore_content.splitlines() if line.strip() and not line.startswith('#')]
        
        # Define what we're looking for and what matches it
        pattern_checks = {
            ".env": [".env", ".env*"],
            "__pycache__": ["__pycache__/", "__pycache__"],  
            "*.pyc": ["*.py[cod]", "*.pyc", "*$py.class"],
            "data/": ["data/"]
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
        with open(req_file, 'r') as f:
            requirements = f.read()
        
        essential_deps = [
            "pandas",
            "yfinance", 
            "python-dotenv",
            "pydantic-settings",
            "sqlalchemy",
            "discord.py"
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
        print("3. On remote environment: python setup.py")
        return True
    else:
        print("❌ VALIDATION FAILED - Please fix the issues above")
        return False

if __name__ == "__main__":
    success = validate_codebase()
    sys.exit(0 if success else 1)
