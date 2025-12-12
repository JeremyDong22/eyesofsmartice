#!/usr/bin/env python3
"""
# Created: 2025-11-16
# Modified: 2025-11-16 - Main entry point for ASE surveillance system
# Feature: Unified entry point for system initialization and startup

ASE Restaurant Surveillance System - Main Entry Point
Version: 4.0.0
Created: 2025-11-16

Purpose:
- Unified entry point for all system operations
- Guides user through initialization vs startup
- Provides clear instructions for production deployment

Usage:
    python3 main.py                    # Interactive mode (choose action)
    python3 main.py --configure        # Configure system (cameras, ROI, etc.)
    python3 main.py --start            # Start service (for development/testing)
    python3 main.py --help             # Show help message

Production Deployment:
1. First time:
   python3 main.py --configure         # Configure all settings
   sudo systemctl start ase_surveillance  # Start with systemd

2. After reboot/crash:
   sudo systemctl status ase_surveillance # Check status
   sudo systemctl restart ase_surveillance # Restart if needed
"""

import sys
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


# Color codes
class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    CYAN = '\033[0;36m'


def show_banner():
    """Display welcome banner"""
    print("\n" + "=" * 72)
    print(f"{Colors.CYAN}{Colors.BOLD}🎥 ASE Restaurant Surveillance System v4.0{Colors.RESET}")
    print("=" * 72)
    print("Production deployment on NVIDIA RTX 3060")
    print("=" * 72 + "\n")


def show_main_menu():
    """Show main menu and get user choice"""
    show_banner()

    print(f"{Colors.BOLD}What would you like to do?{Colors.RESET}\n")
    print("  [1] 🔧 Configure System (cameras, ROI, settings)")
    print("  [2] ℹ️  View Current Configuration")
    print("  [3] 🚀 Start Service (development/testing only)")
    print("  [4] 📖 Production Deployment Guide")
    print("  [5] ❌ Exit\n")

    while True:
        try:
            choice = input("Your choice [1-5]: ").strip()
            if choice in ['1', '2', '3', '4', '5']:
                return choice
            else:
                print(f"{Colors.YELLOW}Invalid choice. Please enter 1-5.{Colors.RESET}")
        except (EOFError, KeyboardInterrupt):
            print(f"\n{Colors.YELLOW}Cancelled by user.{Colors.RESET}\n")
            sys.exit(0)


def configure_system():
    """Run configuration wizard"""
    import subprocess

    initialize_script = SCRIPTS_DIR / "deployment" / "initialize_restaurant.py"

    print(f"\n{Colors.CYAN}Launching configuration wizard...{Colors.RESET}\n")
    result = subprocess.run(["python3", str(initialize_script)])

    return result.returncode == 0


def view_configuration():
    """View current configuration"""
    import json
    from scripts.config import CONFIG_DIR

    CONFIG_DIR = SCRIPTS_DIR / "config"

    print("\n" + "=" * 72)
    print(f"{Colors.BOLD}📋 CURRENT CONFIGURATION{Colors.RESET}")
    print("=" * 72 + "\n")

    # Location
    location_files = list(CONFIG_DIR.glob("*_location.json"))
    if location_files:
        with open(location_files[0]) as f:
            location = json.load(f)
        print(f"{Colors.BOLD}Location:{Colors.RESET}")
        print(f"  Restaurant: {location.get('restaurant_name', 'N/A')}")
        print(f"  City: {location.get('city', 'N/A')}")
        print(f"  Area: {location.get('commercial_area', 'N/A')}\n")
    else:
        print(f"{Colors.YELLOW}⚠️  No location configured{Colors.RESET}\n")

    # Cameras
    cameras_file = CONFIG_DIR / "cameras_config.json"
    if cameras_file.exists():
        with open(cameras_file) as f:
            cameras = json.load(f)
        print(f"{Colors.BOLD}Cameras:{Colors.RESET} {len(cameras)} configured")
        for cam_id, cam_config in cameras.items():
            print(f"  • {cam_id}: {cam_config.get('ip', 'N/A')}")
        print()
    else:
        print(f"{Colors.YELLOW}⚠️  No cameras configured{Colors.RESET}\n")

    # ROI
    roi_files = list(CONFIG_DIR.glob("*_roi.json"))
    print(f"{Colors.BOLD}ROI Configurations:{Colors.RESET} {len(roi_files)} camera(s)\n")

    print("=" * 72 + "\n")
    input("Press ENTER to continue...")


def show_production_guide():
    """Show production deployment guide"""
    print("\n" + "=" * 72)
    print(f"{Colors.BOLD}📖 PRODUCTION DEPLOYMENT GUIDE{Colors.RESET}")
    print("=" * 72 + "\n")

    print(f"{Colors.CYAN}{Colors.BOLD}Step 1: Configure System{Colors.RESET}")
    print("  python3 main.py --configure")
    print("  → Configure cameras, ROI, and all settings\n")

    print(f"{Colors.CYAN}{Colors.BOLD}Step 2: Install Systemd Service{Colors.RESET}")
    print("  sudo cp scripts/deployment/ase_surveillance.service /etc/systemd/system/")
    print("  sudo systemctl daemon-reload")
    print("  sudo systemctl enable ase_surveillance\n")

    print(f"{Colors.CYAN}{Colors.BOLD}Step 3: Start Service{Colors.RESET}")
    print("  sudo systemctl start ase_surveillance\n")

    print(f"{Colors.CYAN}{Colors.BOLD}Management Commands:{Colors.RESET}")
    print("  sudo systemctl status ase_surveillance   # Check status")
    print("  sudo systemctl stop ase_surveillance     # Stop service")
    print("  sudo systemctl restart ase_surveillance  # Restart service")
    print("  sudo journalctl -u ase_surveillance -f   # View logs\n")

    print(f"{Colors.GREEN}{Colors.BOLD}Benefits of Systemd:{Colors.RESET}")
    print("  ✅ Auto-restart on crash")
    print("  ✅ Auto-start on boot")
    print("  ✅ System-level logging")
    print("  ✅ Resource management\n")

    print("=" * 72 + "\n")
    input("Press ENTER to continue...")


def start_service_dev():
    """Start service (development mode)"""
    import subprocess

    print(f"\n{Colors.YELLOW}⚠️  WARNING: Development mode startup{Colors.RESET}")
    print(f"{Colors.YELLOW}For production, use: sudo systemctl start ase_surveillance{Colors.RESET}\n")

    response = input("Continue with development startup? (y/n): ").strip().lower()
    if response not in ['y', 'yes']:
        return

    service_script = SCRIPTS_DIR / "orchestration" / "surveillance_service.py"

    print(f"\n{Colors.CYAN}Starting surveillance service...{Colors.RESET}\n")
    subprocess.run(["python3", str(service_script), "start", "--foreground"])


def main():
    """Main entry point - defaults to configuration wizard"""
    import argparse

    parser = argparse.ArgumentParser(
        description="ASE Surveillance System - Configuration Wizard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Simple 2-step deployment:
  1. python3 main.py                          # Configure everything
  2. sudo systemctl start ase_surveillance    # Start service

That's it!
        """
    )

    parser.add_argument("--view", action="store_true",
                       help="View current configuration (read-only)")

    args = parser.parse_args()

    # View mode
    if args.view:
        view_configuration()
        sys.exit(0)

    # Default: Run configuration wizard
    success = configure_system()

    if success:
        show_systemd_instructions()

    sys.exit(0 if success else 1)


def show_systemd_instructions():
    """Show simple instructions to start with systemd"""
    print("\n" + "=" * 72)
    print(f"{Colors.GREEN}{Colors.BOLD}✅ CONFIGURATION COMPLETE!{Colors.RESET}")
    print("=" * 72 + "\n")

    # Check if systemd service is installed
    import subprocess
    service_installed = subprocess.run(
        ["systemctl", "list-unit-files", "ase_surveillance.service"],
        capture_output=True,
        text=True
    ).returncode == 0

    if not service_installed:
        print(f"{Colors.YELLOW}{Colors.BOLD}⚠️  First time? Install systemd service (ONE-TIME):{Colors.RESET}\n")
        print(f"{Colors.CYAN}  sudo bash scripts/deployment/install_systemd.sh{Colors.RESET}\n")
        print("Then:\n")

    print(f"{Colors.CYAN}{Colors.BOLD}Start Service:{Colors.RESET}")
    print(f"  sudo systemctl start ase_surveillance\n")

    print(f"{Colors.BOLD}Management:{Colors.RESET}")
    print("  sudo systemctl status ase_surveillance   # Check status")
    print("  sudo systemctl stop ase_surveillance     # Stop")
    print("  sudo systemctl restart ase_surveillance  # Restart\n")

    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()
