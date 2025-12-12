#!/usr/bin/env python3
"""
Comprehensive Health Check for Restaurant Surveillance System
Created: 2025-11-20
Purpose: Perform 9-level diagnostic analysis of surveillance infrastructure
"""

import os
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3

class SurveillanceHealthChecker:
    def __init__(self):
        self.base_dir = Path("/home/smartahc/smartice/ASEOfSmartICE/production/RTX_3060")
        self.logs_dir = self.base_dir / "logs"
        self.videos_dir = self.base_dir / "videos"
        self.db_path = self.base_dir / "db" / "detection_data.db"
        self.config_path = self.base_dir / "scripts" / "config" / "cameras_config.json"

        self.report = {
            "timestamp": datetime.now().isoformat(),
            "overall_status": "UNKNOWN",
            "levels": {},
            "critical_issues": [],
            "warnings": [],
            "recommendations": []
        }

    def check_level_1_restart_time(self):
        """Level 1: Restart Time Analysis"""
        try:
            # System uptime
            uptime_output = subprocess.check_output(['uptime', '-s'], text=True).strip()
            last_boot = datetime.strptime(uptime_output, '%Y-%m-%d %H:%M:%S')
            uptime_delta = datetime.now() - last_boot

            # Service start time
            pid_file = self.base_dir / "surveillance_service.pid"
            if pid_file.exists():
                service_start = datetime.fromtimestamp(pid_file.stat().st_mtime)
                service_uptime = datetime.now() - service_start
            else:
                service_start = None
                service_uptime = None

            # Check for recent reboots
            reboot_log = subprocess.check_output(['last', 'reboot', '-3'], text=True)

            self.report["levels"]["1_restart_time"] = {
                "status": "HEALTHY",
                "system_last_boot": last_boot.isoformat(),
                "system_uptime_hours": round(uptime_delta.total_seconds() / 3600, 1),
                "service_start": service_start.isoformat() if service_start else "UNKNOWN",
                "service_uptime_hours": round(service_uptime.total_seconds() / 3600, 1) if service_uptime else 0,
                "recent_reboots": reboot_log.count("reboot")
            }

            if uptime_delta < timedelta(hours=24):
                self.report["warnings"].append(f"System restarted recently ({uptime_delta.total_seconds()/3600:.1f}h ago)")

        except Exception as e:
            self.report["levels"]["1_restart_time"] = {"status": "ERROR", "error": str(e)}

    def check_level_2_maintenance(self):
        """Level 2: Maintenance Level Assessment"""
        try:
            # Check for maintenance logs
            startup_log = self.logs_dir / "startup.log"
            if startup_log.exists():
                file_age = datetime.now() - datetime.fromtimestamp(startup_log.stat().st_mtime)
                log_size = startup_log.stat().st_size / (1024 * 1024)  # MB
            else:
                file_age = None
                log_size = 0

            # Check systemd service status
            systemd_enabled = subprocess.check_output(
                ['systemctl', 'is-enabled', 'ase_surveillance'], text=True
            ).strip() == "enabled"

            self.report["levels"]["2_maintenance"] = {
                "status": "HEALTHY",
                "systemd_service_enabled": systemd_enabled,
                "startup_log_size_mb": round(log_size, 2),
                "startup_log_age_hours": round(file_age.total_seconds() / 3600, 1) if file_age else "N/A"
            }

        except Exception as e:
            self.report["levels"]["2_maintenance"] = {"status": "ERROR", "error": str(e)}

    def check_level_3_deployment(self):
        """Level 3: Deployment Level Verification"""
        try:
            # Check camera configuration
            if self.config_path.exists():
                with open(self.config_path) as f:
                    cameras = json.load(f)
                camera_count = len(cameras)
                enabled_count = sum(1 for c in cameras.values() if c.get("enabled", True))
            else:
                camera_count = 0
                enabled_count = 0

            # Check models
            models_dir = self.base_dir / "models"
            person_model = models_dir / "yolov8m.pt"
            classifier_model = models_dir / "waiter_customer_classifier.pt"

            models_ok = person_model.exists() and classifier_model.exists()

            # Check ROI configuration
            roi_config = self.base_dir / "scripts" / "config" / "table_region_config.json"
            roi_configured = roi_config.exists()

            status = "HEALTHY" if models_ok and camera_count > 0 else "WARNING"

            self.report["levels"]["3_deployment"] = {
                "status": status,
                "cameras_configured": camera_count,
                "cameras_enabled": enabled_count,
                "person_model_present": person_model.exists(),
                "classifier_model_present": classifier_model.exists(),
                "roi_configuration": "CONFIGURED" if roi_configured else "MISSING"
            }

            # Camera count check removed - testing with 1 camera currently
            # if camera_count < 1:
            #     self.report["warnings"].append(f"No cameras configured")

            if not models_ok:
                self.report["critical_issues"].append("YOLO models missing from deployment")

        except Exception as e:
            self.report["levels"]["3_deployment"] = {"status": "ERROR", "error": str(e)}

    def check_level_4_monitoring(self):
        """Level 4: Monitoring Level Health"""
        try:
            # Check surveillance service log
            service_log = self.logs_dir / "surveillance_service.log"

            if service_log.exists():
                # Get recent health checks
                with open(service_log, 'r') as f:
                    lines = f.readlines()
                    health_checks = [l for l in lines[-100:] if "Health check:" in l]

                if health_checks:
                    last_check = health_checks[-1]
                    # Extract status from log
                    import re
                    match = re.search(r"'capture_running': (\w+), 'processing_running': (\w+)", last_check)
                    if match:
                        capture_running = match.group(1) == "True"
                        processing_running = match.group(2) == "True"
                    else:
                        capture_running = None
                        processing_running = None
                else:
                    capture_running = None
                    processing_running = None

                log_age = datetime.now() - datetime.fromtimestamp(service_log.stat().st_mtime)
                monitoring_active = log_age < timedelta(minutes=60)
            else:
                capture_running = None
                processing_running = None
                monitoring_active = False

            # Check actual processes
            capture_proc = subprocess.run(
                ['pgrep', '-f', 'capture_rtsp_streams.py'],
                capture_output=True
            ).returncode == 0

            processing_proc = subprocess.run(
                ['pgrep', '-f', 'batch_process_videos.py'],
                capture_output=True
            ).returncode == 0

            status = "HEALTHY" if monitoring_active else "WARNING"

            self.report["levels"]["4_monitoring"] = {
                "status": status,
                "monitoring_active": monitoring_active,
                "capture_process_running": capture_proc,
                "processing_process_running": processing_proc,
                "reported_capture_status": capture_running,
                "reported_processing_status": processing_running
            }

            if not monitoring_active:
                self.report["warnings"].append("Monitoring logs not updating (last update >1h ago)")

        except Exception as e:
            self.report["levels"]["4_monitoring"] = {"status": "ERROR", "error": str(e)}

    def check_level_5_orchestration(self):
        """Level 5: Orchestration Level Status"""
        try:
            # Check surveillance service process
            service_proc = subprocess.run(
                ['pgrep', '-f', 'surveillance_service.py'],
                capture_output=True, text=True
            )
            service_running = service_proc.returncode == 0

            if service_running:
                pid = service_proc.stdout.strip()
                # Get process details
                ps_output = subprocess.check_output(
                    ['ps', '-p', pid, '-o', 'pid,ppid,etime,cmd', '--no-headers'],
                    text=True
                )
            else:
                ps_output = None

            # Check for zombie processes
            zombies = subprocess.check_output(
                ['ps', 'aux'], text=True
            ).count('<defunct>')

            status = "HEALTHY" if service_running and zombies == 0 else "CRITICAL"

            self.report["levels"]["5_orchestration"] = {
                "status": status,
                "surveillance_service_running": service_running,
                "service_details": ps_output.strip() if ps_output else "NOT_RUNNING",
                "zombie_processes": zombies
            }

            if not service_running:
                self.report["critical_issues"].append("Surveillance service not running")

            if zombies > 0:
                self.report["warnings"].append(f"Found {zombies} zombie processes")

        except Exception as e:
            self.report["levels"]["5_orchestration"] = {"status": "ERROR", "error": str(e)}

    def check_level_6_time_sync(self):
        """Level 6: Time Synchronization Check"""
        try:
            # Check NTP sync status
            timedatectl = subprocess.check_output(['timedatectl', 'status'], text=True)

            sync_enabled = "System clock synchronized: yes" in timedatectl
            ntp_active = "NTP service: active" in timedatectl

            # Extract timezone
            import re
            tz_match = re.search(r'Time zone: ([^\(]+)', timedatectl)
            timezone = tz_match.group(1).strip() if tz_match else "UNKNOWN"

            status = "HEALTHY" if sync_enabled and ntp_active else "WARNING"

            self.report["levels"]["6_time_sync"] = {
                "status": status,
                "ntp_synchronized": sync_enabled,
                "ntp_service_active": ntp_active,
                "timezone": timezone
            }

            if not sync_enabled:
                self.report["warnings"].append("NTP time synchronization not active")

        except Exception as e:
            self.report["levels"]["6_time_sync"] = {"status": "ERROR", "error": str(e)}

    def check_level_7_video_capture(self):
        """Level 7: Video Capture Operations"""
        try:
            # Check today's captures
            today = datetime.now().strftime("%Y%m%d")
            today_dir = self.videos_dir / today / "camera_35"

            if today_dir.exists():
                video_files = list(today_dir.glob("*.mp4"))
                total_size_gb = sum(f.stat().st_size for f in video_files) / (1024**3)

                # Check if actively recording
                if video_files:
                    latest_file = max(video_files, key=lambda f: f.stat().st_mtime)
                    latest_age = datetime.now() - datetime.fromtimestamp(latest_file.stat().st_mtime)
                    actively_recording = latest_age < timedelta(minutes=15)
                else:
                    actively_recording = False
                    latest_age = None
            else:
                video_files = []
                total_size_gb = 0
                actively_recording = False
                latest_age = None

            # Check camera connectivity (RTSP)
            # We'll assume if files are being created, camera is connected
            camera_connected = actively_recording

            # Current hour
            current_hour = datetime.now().hour
            should_be_capturing = (11 <= current_hour < 14) or (17 <= current_hour < 22)

            if should_be_capturing and not actively_recording:
                status = "CRITICAL"
            elif actively_recording:
                status = "HEALTHY"
            else:
                status = "IDLE"

            self.report["levels"]["7_video_capture"] = {
                "status": status,
                "today_video_count": len(video_files),
                "today_total_size_gb": round(total_size_gb, 2),
                "actively_recording": actively_recording,
                "latest_file_age_minutes": round(latest_age.total_seconds() / 60, 1) if latest_age else None,
                "camera_connected": camera_connected,
                "should_be_capturing": should_be_capturing
            }

            if should_be_capturing and not actively_recording:
                self.report["critical_issues"].append("Camera should be capturing but no recent files detected")

        except Exception as e:
            self.report["levels"]["7_video_capture"] = {"status": "ERROR", "error": str(e)}

    def check_level_8_processing_pipeline(self):
        """Level 8: Video Processing Pipeline"""
        try:
            # Check recent processing logs
            processing_logs = sorted(self.logs_dir.glob("processing_*.log"),
                                   key=lambda f: f.stat().st_mtime,
                                   reverse=True)

            if processing_logs:
                latest_log = processing_logs[0]
                with open(latest_log, 'r') as f:
                    log_content = f.read()

                # Parse success/failure
                import re
                completed_match = re.search(r'Completed: (\d+)', log_content)
                failed_match = re.search(r'Failed: (\d+)', log_content)
                success_rate_match = re.search(r'Success rate: ([\d.]+)%', log_content)

                completed = int(completed_match.group(1)) if completed_match else 0
                failed = int(failed_match.group(1)) if failed_match else 0
                success_rate = float(success_rate_match.group(1)) if success_rate_match else 0

                log_age = datetime.now() - datetime.fromtimestamp(latest_log.stat().st_mtime)

                # Check for moov atom errors (corrupted videos)
                moov_errors = log_content.count("moov atom not found")
            else:
                completed = 0
                failed = 0
                success_rate = 0
                log_age = None
                moov_errors = 0

            # Check results directory
            results_dir = self.base_dir / "results"
            if results_dir.exists():
                result_files = list(results_dir.rglob("*.mp4"))
                results_count = len(result_files)
            else:
                results_count = 0

            if success_rate >= 80:
                status = "HEALTHY"
            elif success_rate >= 50:
                status = "WARNING"
            else:
                status = "CRITICAL"

            self.report["levels"]["8_processing_pipeline"] = {
                "status": status,
                "last_processing_completed": completed,
                "last_processing_failed": failed,
                "success_rate_percent": success_rate,
                "last_log_age_minutes": round(log_age.total_seconds() / 60, 1) if log_age else None,
                "moov_atom_errors": moov_errors,
                "processed_results_count": results_count
            }

            if moov_errors > 10:
                self.report["critical_issues"].append(
                    f"High number of corrupted video files ({moov_errors} moov atom errors)"
                )

            if success_rate == 0 and (completed + failed) > 0:
                self.report["critical_issues"].append("Video processing failing for all files")

        except Exception as e:
            self.report["levels"]["8_processing_pipeline"] = {"status": "ERROR", "error": str(e)}

    def check_level_9_database_io(self):
        """Level 9: Database I/O Audit"""
        try:
            # Check database file
            if self.db_path.exists():
                db_size_mb = self.db_path.stat().st_size / (1024 * 1024)

                # Query database
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()

                # Count sessions
                cursor.execute("SELECT COUNT(*) FROM sessions")
                session_count = cursor.fetchone()[0]

                # Count state changes
                try:
                    cursor.execute("SELECT COUNT(*) FROM division_states")
                    division_states = cursor.fetchone()[0]
                except:
                    division_states = 0

                try:
                    cursor.execute("SELECT COUNT(*) FROM table_states")
                    table_states = cursor.fetchone()[0]
                except:
                    table_states = 0

                conn.close()

                db_functional = True
            else:
                db_size_mb = 0
                session_count = 0
                division_states = 0
                table_states = 0
                db_functional = False

            # Check Supabase sync (environment variables)
            supabase_configured = (
                os.getenv("SUPABASE_URL") is not None and
                os.getenv("SUPABASE_ANON_KEY") is not None
            )

            # Check error logs for upload failures
            errors_log = self.logs_dir / f"errors_{datetime.now().strftime('%Y%m%d')}.log"
            if errors_log.exists():
                with open(errors_log, 'r') as f:
                    error_content = f.read()
                upload_errors = error_content.count("upload") + error_content.count("Supabase")
            else:
                upload_errors = 0

            status = "HEALTHY" if db_functional else "WARNING"

            self.report["levels"]["9_database_io"] = {
                "status": status,
                "database_size_mb": round(db_size_mb, 2),
                "database_functional": db_functional,
                "sessions_recorded": session_count,
                "division_state_changes": division_states,
                "table_state_changes": table_states,
                "supabase_configured": supabase_configured,
                "upload_errors_today": upload_errors
            }

            if not supabase_configured:
                self.report["warnings"].append("Supabase credentials not configured - cloud sync disabled")

            if session_count == 0:
                self.report["warnings"].append("No processing sessions recorded in database")

        except Exception as e:
            self.report["levels"]["9_database_io"] = {"status": "ERROR", "error": str(e)}

    def determine_overall_status(self):
        """Determine overall system health"""
        statuses = [level.get("status", "UNKNOWN") for level in self.report["levels"].values()]

        if "CRITICAL" in statuses or len(self.report["critical_issues"]) > 0:
            self.report["overall_status"] = "CRITICAL"
        elif "ERROR" in statuses:
            self.report["overall_status"] = "ERROR"
        elif "WARNING" in statuses or len(self.report["warnings"]) > 0:
            self.report["overall_status"] = "DEGRADED"
        else:
            self.report["overall_status"] = "HEALTHY"

    def generate_recommendations(self):
        """Generate actionable recommendations"""
        # Video corruption issues
        if any("moov atom" in str(level) for level in self.report["levels"].values()):
            self.report["recommendations"].append(
                "CRITICAL: Multiple corrupted video files detected. "
                "This indicates improper video file termination during capture. "
                "Recommend investigating capture script signal handling and file finalization logic."
            )

        # Supabase sync
        if not self.report["levels"].get("9_database_io", {}).get("supabase_configured", False):
            self.report["recommendations"].append(
                "Configure Supabase credentials (SUPABASE_URL and SUPABASE_ANON_KEY) "
                "to enable cloud backup and remote monitoring."
            )

        # Processing failures
        processing = self.report["levels"].get("8_processing_pipeline", {})
        if processing.get("success_rate_percent", 100) < 50:
            self.report["recommendations"].append(
                "Video processing success rate below 50%. "
                "Check for video corruption, model availability, and GPU memory issues."
            )

        # Disk space
        # Add disk space check recommendation if needed
        self.report["recommendations"].append(
            "Run disk space monitoring: python3 scripts/monitoring/check_disk_space.py --check"
        )

    def run_full_diagnostic(self):
        """Execute all 9 diagnostic levels"""
        print("=" * 80)
        print("RESTAURANT SURVEILLANCE SYSTEM - COMPREHENSIVE HEALTH CHECK")
        print("=" * 80)
        print(f"Timestamp: {self.report['timestamp']}")
        print()

        checks = [
            ("Level 1: Restart Time Analysis", self.check_level_1_restart_time),
            ("Level 2: Maintenance Assessment", self.check_level_2_maintenance),
            ("Level 3: Deployment Verification", self.check_level_3_deployment),
            ("Level 4: Monitoring Health", self.check_level_4_monitoring),
            ("Level 5: Orchestration Status", self.check_level_5_orchestration),
            ("Level 6: Time Synchronization", self.check_level_6_time_sync),
            ("Level 7: Video Capture Operations", self.check_level_7_video_capture),
            ("Level 8: Video Processing Pipeline", self.check_level_8_processing_pipeline),
            ("Level 9: Database I/O Audit", self.check_level_9_database_io),
        ]

        for name, check_func in checks:
            print(f"Running {name}...")
            check_func()

        self.determine_overall_status()
        self.generate_recommendations()

        return self.report

    def print_report(self):
        """Print formatted health report"""
        print("\n" + "=" * 80)
        print("EXECUTIVE SUMMARY")
        print("=" * 80)
        print(f"Overall Status: {self.report['overall_status']}")
        print(f"Timestamp: {self.report['timestamp']}")
        print()

        print("=" * 80)
        print("LEVEL-BY-LEVEL ASSESSMENT")
        print("=" * 80)

        for level_name, level_data in self.report["levels"].items():
            status = level_data.get("status", "UNKNOWN")
            symbol = {"HEALTHY": "✓", "WARNING": "⚠", "CRITICAL": "✗", "ERROR": "✗", "IDLE": "○"}.get(status, "?")

            print(f"\n{symbol} {level_name.replace('_', ' ').title()}: {status}")
            for key, value in level_data.items():
                if key != "status":
                    print(f"  - {key}: {value}")

        if self.report["critical_issues"]:
            print("\n" + "=" * 80)
            print("CRITICAL ISSUES")
            print("=" * 80)
            for issue in self.report["critical_issues"]:
                print(f"✗ {issue}")

        if self.report["warnings"]:
            print("\n" + "=" * 80)
            print("WARNINGS")
            print("=" * 80)
            for warning in self.report["warnings"]:
                print(f"⚠ {warning}")

        if self.report["recommendations"]:
            print("\n" + "=" * 80)
            print("RECOMMENDATIONS")
            print("=" * 80)
            for i, rec in enumerate(self.report["recommendations"], 1):
                print(f"{i}. {rec}")

        print("\n" + "=" * 80)
        print("END OF HEALTH REPORT")
        print("=" * 80)

if __name__ == "__main__":
    checker = SurveillanceHealthChecker()
    checker.run_full_diagnostic()
    checker.print_report()

    # Save to JSON
    output_file = checker.base_dir / "logs" / f"health_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w') as f:
        json.dump(checker.report, f, indent=2)

    print(f"\nReport saved to: {output_file}")
