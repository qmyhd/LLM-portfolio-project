import os
import subprocess
import sys
from pathlib import Path


def main():
    # Locate the web directory
    root_dir = Path(__file__).parent.parent
    web_dir = root_dir / "web" / "arb-dashboard"

    if not web_dir.exists():
        print(f"Error: Directory {web_dir} not found.")
        sys.exit(1)

    print(f"Starting Arb Dashboard in {web_dir}...")
    os.chdir(web_dir)

    # Check if node_modules exists
    if not (web_dir / "node_modules").exists():
        print("Installing dependencies (npm install)...")
        try:
            subprocess.check_call(["npm", "install"], shell=True)
        except subprocess.CalledProcessError:
            print("Error: npm install failed. Do you have Node.js installed?")
            sys.exit(1)

    # Run dev server
    print("Starting dev server (npm run dev)...")
    try:
        subprocess.check_call(["npm", "run", "dev"], shell=True)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
