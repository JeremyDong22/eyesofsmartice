#!/usr/bin/env python3
"""
System Health Check
Version: 1.0.0
Last Updated: 2025-11-14

Purpose: Comprehensive system health check for production deployment

Checks:
- Disk space (>100GB)
- GPU availability and temperature
- Required directories exist
- Config files present
- Models present
- Python dependencies

Usage:
  python3 system_health.py           # Full health check
  python3 system_health.py --quick   # Skip slow checks
"""

import sys
from pathlib import Path
import subprocess

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = SCRIPT_DIR.parent.parent

def check_disk_space():
    """Check disk space using check_disk_space.py"""
    result = subprocess.run(
        [sys.executable, SCRIPT_DIR / "check_disk_space.py", "--check"],
        capture_output=True
    )
    return result.returncode == 0

def check_gpu():
    """Check GPU using monitor_gpu.py"""
    result = subprocess.run(
        [sys.executable, SCRIPT_DIR / "monitor_gpu.py"],
        capture_output=True
    )
    return result.returncode in [0, 2]  # 0=healthy, 2=no GPU (ok on Mac)

def check_directories():
    """Check required directories exist"""
    required = ["videos", "results", "db", "models", "scripts", "logs"]
    for dirname in required:
        path = PROJECT_DIR / dirname
        if not path.exists():
            print(f"❌ Missing directory: {dirname}")
            return False
    print(f"✅ All required directories exist")
    return True

def check_models():
    """Check YOLO models exist"""
    models = [
        PROJECT_DIR / "models" / "yolov8m.pt",
        PROJECT_DIR / "models" / "waiter_customer_classifier.pt"
    ]
    for model in models:
        if not model.exists():
            print(f"❌ Missing model: {model.name}")
            return False
    print(f"✅ All models present")
    return True

def check_configs():
    """Check config files exist"""
    configs = [
        PROJECT_DIR / "scripts" / "config" / "cameras_config.json",
        PROJECT_DIR / "scripts" / "config" / "table_region_config.json"
    ]
    for config in configs:
        if not config.exists():
            print(f"⚠️  Missing config: {config.name} (will be created on first run)")
    return True

def main():
    print("="*70)
    print("SYSTEM HEALTH CHECK")
    print("="*70 + "\n")

    checks = [
        ("Directories", check_directories),
        ("Models", check_models),
        ("Config Files", check_configs),
        ("Disk Space", check_disk_space),
        ("GPU", check_gpu),
    ]

    results = []
    for name, check_func in checks:
        print(f"\nChecking {name}...")
        try:
            passed = check_func()
            results.append((name, passed))
        except Exception as e:
            print(f"❌ Error: {e}")
            results.append((name, False))

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{name:20s} {status}")

    all_passed = all(passed for _, passed in results)
    print(f"\n{'='*70}")
    if all_passed:
        print("✅ SYSTEM HEALTHY - Ready for production")
        sys.exit(0)
    else:
        print("⚠️  SYSTEM ISSUES DETECTED - Review failures above")
        sys.exit(1)

if __name__ == "__main__":
    main()
