#!/usr/bin/env python3
"""
# Created: 2025-11-16
# Modified: 2025-11-16 - Complete system configuration wizard
# Feature: All-in-one configuration tool (NO startup - use systemd)

ASE Restaurant Surveillance System - Configuration Wizard v4.0

Purpose:
- Complete system configuration (cameras, ROI, settings)
- Interactive camera management (add/edit/delete/test)
- ROI configuration with interactive drawing
- System health checks
- NO SERVICE STARTUP (use systemd instead)

Usage:
    python3 scripts/deployment/initialize_restaurant.py

After configuration:
    sudo systemctl start ase_surveillance
"""

# Import the interactive wizard (keep all configuration code)
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from interactive_start import InteractiveStartup, Colors

class SystemConfiguration(InteractiveStartup):
    """Configuration wizard (extends InteractiveStartup, removes startup)"""
    
    def __init__(self, quick_mode=False):
        super().__init__(quick_mode=quick_mode, test_only=True)
    
    def show_completion_message(self):
        """Show completion message with systemd instructions"""
        print("\n" + "=" * 72)
        print(f"{Colors.GREEN}{Colors.BOLD}✅ SYSTEM CONFIGURATION COMPLETE!{Colors.RESET}")
        print("=" * 72 + "\n")
        
        print(f"{Colors.CYAN}{Colors.BOLD}Next Steps - Start Service:{Colors.RESET}\n")
        
        print(f"{Colors.BOLD}For Production (Recommended):{Colors.RESET}")
        print("  sudo systemctl start ase_surveillance\n")
        
        print(f"{Colors.BOLD}Management Commands:{Colors.RESET}")
        print("  sudo systemctl status ase_surveillance   # Check status")
        print("  sudo systemctl stop ase_surveillance     # Stop")
        print("  sudo systemctl restart ase_surveillance  # Restart")
        print("  sudo journalctl -u ase_surveillance -f   # View logs\n")
        
        print(f"{Colors.BOLD}Benefits of Systemd:{Colors.RESET}")
        print("  ✅ Auto-restart on crash")
        print("  ✅ Auto-start on boot")
        print("  ✅ System-level resource management")
        print("  ✅ Integrated logging\n")
        
        print("=" * 72 + "\n")
    
    def run(self):
        """Override run() to remove startup prompts"""
        try:
            # Step 1: Welcome and pre-flight checks
            self.show_welcome()
            if not self.run_preflight_checks():
                return False

            # Step 2: Configuration review loop
            while True:
                self.load_all_configuration()
                self.display_configuration_review()

                if self.quick_mode:
                    break

                choice = self.prompt_menu(
                    "IS THIS CONFIGURATION CORRECT?",
                    [
                        ("continue", "✅ Yes - Continue to camera testing"),
                        ("edit", "📝 Edit configuration (interactive menu)"),
                        ("reload", "🔄 Reload from disk"),
                        ("exit", "❌ Exit")
                    ]
                )

                if choice == "continue":
                    break
                elif choice == "edit":
                    self.interactive_editor()
                elif choice == "reload":
                    continue
                elif choice == "exit":
                    return False

            # Step 3: Camera testing
            if not self.test_all_cameras_workflow():
                return False

            # Step 3.5: ROI configuration
            if not self.quick_mode:
                if not self.configure_roi_for_cameras():
                    return False

            # Step 4: Feature overview
            self.show_feature_overview()

            # Step 5: Show completion message (NO STARTUP)
            self.show_completion_message()
            return True

        except KeyboardInterrupt:
            print(f"\n\n{Colors.YELLOW}⚠️  Interrupted by user{Colors.RESET}\n")
            return False
        except Exception as e:
            print(f"\n\n{Colors.RED}❌ Fatal error: {e}{Colors.RESET}")
            import traceback
            traceback.print_exc()
            return False


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description="ASE Surveillance System - Configuration Wizard",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("--quick", action="store_true",
                       help="Quick mode (skip confirmations)")

    args = parser.parse_args()

    wizard = SystemConfiguration(quick_mode=args.quick)
    success = wizard.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
