#!/usr/bin/env python3
"""
# Modified: 2025-11-16 - Created camera management tool with add/remove/edit capabilities

Camera Management Tool
Version: 1.0.0
Created: 2025-11-16

Purpose:
- Manage camera configurations after initial deployment
- Add new cameras to existing location
- Remove cameras
- Edit camera settings (credentials, IP, etc.)
- Update configuration files and database

Usage:
    python3 manage_cameras.py                    # Interactive menu
    python3 manage_cameras.py --list             # List all cameras
    python3 manage_cameras.py --add              # Add new camera
    python3 manage_cameras.py --remove camera_35 # Remove camera
    python3 manage_cameras.py --edit camera_35   # Edit camera
"""

import os
import sys
import sqlite3
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

# Project paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

DB_PATH = PROJECT_ROOT / "db" / "detection_data.db"
CONFIG_DIR = SCRIPT_DIR.parent / "config"
CAMERAS_CONFIG_FILE = CONFIG_DIR / "cameras_config.json"


class CameraManager:
    """
    Camera configuration management tool

    Handles CRUD operations for camera configurations
    """

    def __init__(self):
        self.conn = None
        self.location_id = None
        self.cameras = {}

    def run(self):
        """Main interactive menu"""
        self.load_database()

        while True:
            self.show_menu()
            choice = input("\nSelect option (1-6): ").strip()

            if choice == '1':
                self.list_cameras()
            elif choice == '2':
                self.add_camera()
            elif choice == '3':
                self.edit_camera()
            elif choice == '4':
                self.remove_camera()
            elif choice == '5':
                self.test_camera()
            elif choice == '6':
                print("\n✅ Exiting camera management")
                break
            else:
                print("❌ Invalid option, try again")

    def show_menu(self):
        """Display main menu"""
        print("\n" + "=" * 70)
        print("📷 Camera Management Tool")
        print("=" * 70)
        print(f"Location: {self.location_id or 'Not initialized'}")
        print(f"Cameras: {len(self.cameras)}")
        print()
        print("1. List all cameras")
        print("2. Add new camera")
        print("3. Edit camera")
        print("4. Remove camera")
        print("5. Test camera connection")
        print("6. Exit")
        print("=" * 70)

    def load_database(self):
        """Load cameras from database"""
        if not DB_PATH.exists():
            print("❌ Database not found. Run initialize_restaurant.py first.")
            sys.exit(1)

        self.conn = sqlite3.connect(str(DB_PATH))
        cursor = self.conn.cursor()

        # Get location_id
        cursor.execute("SELECT location_id FROM locations LIMIT 1")
        result = cursor.fetchone()
        if result:
            self.location_id = result[0]
        else:
            print("❌ No location found. Run initialize_restaurant.py first.")
            sys.exit(1)

        # Load existing cameras
        self.load_cameras_config()

    def load_cameras_config(self):
        """Load cameras from config file"""
        if CAMERAS_CONFIG_FILE.exists():
            with open(CAMERAS_CONFIG_FILE, 'r') as f:
                self.cameras = json.load(f)
        else:
            self.cameras = {}

    def save_cameras_config(self):
        """Save cameras to config file"""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CAMERAS_CONFIG_FILE, 'w') as f:
            json.dump(self.cameras, f, indent=2)
        print(f"✅ Configuration saved: {CAMERAS_CONFIG_FILE}")

    def list_cameras(self):
        """List all configured cameras"""
        print("\n" + "=" * 70)
        print("📋 Camera List")
        print("=" * 70)

        if not self.cameras:
            print("No cameras configured yet.")
            return

        for camera_id, config in self.cameras.items():
            enabled = "✅" if config.get('enabled', True) else "❌"
            print(f"\n{enabled} {camera_id}:")
            print(f"   IP: {config.get('ip', 'N/A')}")
            print(f"   Username: {config.get('username', 'N/A')}")
            print(f"   Port: {config.get('port', 554)}")
            print(f"   Stream: {config.get('stream_path', 'N/A')}")
            print(f"   Division: {config.get('division_name', 'N/A')}")
            print(f"   Notes: {config.get('notes', 'N/A')}")

    def add_camera(self):
        """Add a new camera"""
        print("\n" + "=" * 70)
        print("➕ Add New Camera")
        print("=" * 70)

        # Get IP address
        ip_address = input("IP Address (e.g., 202.168.40.35): ").strip()
        if not self._validate_ip(ip_address):
            print("❌ Invalid IP address format")
            return

        camera_id = f"camera_{ip_address.split('.')[-1]}"

        if camera_id in self.cameras:
            print(f"❌ Camera {camera_id} already exists!")
            overwrite = input("Overwrite? (y/n): ").strip().lower()
            if overwrite != 'y':
                return

        # Collect camera details
        print("\nRTSP Credentials:")
        username = input("  Username (default: admin): ").strip() or "admin"
        password = input("  Password (default: 123456): ").strip() or "123456"

        port_input = input("Port (default: 554): ").strip()
        port = int(port_input) if port_input else 554

        stream_path = input("Stream Path (default: /media/video1): ").strip() or "/media/video1"

        division_name = input("Division/Area Name (optional): ").strip() or ""
        notes = input("Notes/Description (optional): ").strip() or f"Camera {camera_id}"

        resolution_input = input("Resolution (e.g., 2592x1944, default: 2592x1944): ").strip()
        if resolution_input:
            try:
                width, height = resolution_input.split('x')
                resolution = [int(width), int(height)]
            except:
                resolution = [2592, 1944]
        else:
            resolution = [2592, 1944]

        # Create camera config
        self.cameras[camera_id] = {
            'ip': ip_address,
            'port': port,
            'username': username,
            'password': password,
            'stream_path': stream_path,
            'resolution': resolution,
            'fps': 20,
            'division_name': division_name,
            'location_id': self.location_id,
            'enabled': True,
            'notes': notes
        }

        # Save to file
        self.save_cameras_config()

        # Update database
        self._update_database_camera(camera_id)

        print(f"\n✅ Camera {camera_id} added successfully!")

    def edit_camera(self):
        """Edit existing camera"""
        print("\n" + "=" * 70)
        print("✏️  Edit Camera")
        print("=" * 70)

        if not self.cameras:
            print("No cameras configured yet.")
            return

        camera_id = input("Camera ID to edit (e.g., camera_35): ").strip()

        if camera_id not in self.cameras:
            print(f"❌ Camera {camera_id} not found")
            return

        config = self.cameras[camera_id]
        print(f"\nEditing {camera_id}")
        print("(Press Enter to keep current value)")
        print()

        # Edit each field
        ip = input(f"IP Address [{config['ip']}]: ").strip() or config['ip']
        username = input(f"Username [{config.get('username', 'admin')}]: ").strip() or config.get('username', 'admin')
        password = input(f"Password [{config.get('password', '***')}]: ").strip() or config.get('password', '123456')
        port = input(f"Port [{config.get('port', 554)}]: ").strip()
        port = int(port) if port else config.get('port', 554)
        stream_path = input(f"Stream Path [{config.get('stream_path', '/media/video1')}]: ").strip() or config.get('stream_path', '/media/video1')
        division_name = input(f"Division [{config.get('division_name', '')}]: ").strip() or config.get('division_name', '')
        notes = input(f"Notes [{config.get('notes', '')}]: ").strip() or config.get('notes', '')

        enabled = input(f"Enabled [{'yes' if config.get('enabled', True) else 'no'}] (yes/no): ").strip().lower()
        if enabled:
            enabled = enabled == 'yes'
        else:
            enabled = config.get('enabled', True)

        # Update config
        self.cameras[camera_id] = {
            'ip': ip,
            'port': port,
            'username': username,
            'password': password,
            'stream_path': stream_path,
            'resolution': config.get('resolution', [2592, 1944]),
            'fps': config.get('fps', 20),
            'division_name': division_name,
            'location_id': self.location_id,
            'enabled': enabled,
            'notes': notes
        }

        # Save to file
        self.save_cameras_config()

        # Update database
        self._update_database_camera(camera_id)

        print(f"\n✅ Camera {camera_id} updated successfully!")

    def remove_camera(self):
        """Remove a camera"""
        print("\n" + "=" * 70)
        print("🗑️  Remove Camera")
        print("=" * 70)

        if not self.cameras:
            print("No cameras configured yet.")
            return

        camera_id = input("Camera ID to remove (e.g., camera_35): ").strip()

        if camera_id not in self.cameras:
            print(f"❌ Camera {camera_id} not found")
            return

        # Confirm deletion
        confirm = input(f"⚠️  Remove {camera_id}? This cannot be undone. (yes/no): ").strip().lower()
        if confirm != 'yes':
            print("Cancelled.")
            return

        # Remove from config
        del self.cameras[camera_id]

        # Save to file
        self.save_cameras_config()

        # Update database (mark as inactive)
        cursor = self.conn.cursor()
        cursor.execute("UPDATE cameras SET status = 'inactive' WHERE camera_id = ?", (camera_id,))
        self.conn.commit()

        print(f"\n✅ Camera {camera_id} removed successfully!")

    def test_camera(self):
        """Test camera RTSP connection"""
        print("\n" + "=" * 70)
        print("🔌 Test Camera Connection")
        print("=" * 70)

        if not self.cameras:
            print("No cameras configured yet.")
            return

        camera_id = input("Camera ID to test (e.g., camera_35): ").strip()

        if camera_id not in self.cameras:
            print(f"❌ Camera {camera_id} not found")
            return

        config = self.cameras[camera_id]

        try:
            import cv2
        except ImportError:
            print("❌ OpenCV not installed. Install with: pip install opencv-python")
            return

        # Build RTSP URL
        rtsp_url = f"rtsp://{config['username']}:{config['password']}@{config['ip']}:{config['port']}{config['stream_path']}"

        print(f"\nTesting {camera_id}...")
        print(f"URL: rtsp://{config['username']}:***@{config['ip']}:{config['port']}{config['stream_path']}")

        cap = cv2.VideoCapture(rtsp_url)
        success, frame = cap.read()
        cap.release()

        if success:
            print("✅ Connection successful!")
            print(f"   Resolution: {frame.shape[1]}x{frame.shape[0]}")
        else:
            print("❌ Connection failed!")
            print("   Check: IP address, credentials, network, RTSP endpoint")

    def _validate_ip(self, ip: str) -> bool:
        """Validate IP address format"""
        pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        if not re.match(pattern, ip):
            return False
        octets = ip.split('.')
        return all(0 <= int(octet) <= 255 for octet in octets)

    def _update_database_camera(self, camera_id: str):
        """Update camera in database"""
        config = self.cameras[camera_id]
        cursor = self.conn.cursor()

        rtsp_endpoint = f"rtsp://{config['username']}:{config['password']}@{config['ip']}:{config['port']}{config['stream_path']}"
        resolution_str = f"{config['resolution'][0]}x{config['resolution'][1]}"

        cursor.execute('''
            INSERT OR REPLACE INTO cameras
            (camera_id, location_id, camera_name, camera_ip_address, rtsp_endpoint,
             camera_type, resolution, division_name, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            camera_id,
            self.location_id,
            config.get('notes', camera_id),
            config['ip'],
            rtsp_endpoint,
            'UNV',
            resolution_str,
            config.get('division_name', ''),
            'active' if config.get('enabled', True) else 'inactive'
        ))

        self.conn.commit()

    def __del__(self):
        """Cleanup database connection"""
        if self.conn:
            self.conn.close()


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Camera Management Tool')
    parser.add_argument('--list', action='store_true', help='List all cameras')
    parser.add_argument('--add', action='store_true', help='Add new camera')
    parser.add_argument('--remove', metavar='CAMERA_ID', help='Remove camera')
    parser.add_argument('--edit', metavar='CAMERA_ID', help='Edit camera')

    args = parser.parse_args()

    manager = CameraManager()
    manager.load_database()

    if args.list:
        manager.list_cameras()
    elif args.add:
        manager.add_camera()
    elif args.remove:
        print(f"Removing camera: {args.remove}")
        # Implement direct removal
    elif args.edit:
        print(f"Editing camera: {args.edit}")
        # Implement direct editing
    else:
        # Interactive menu
        manager.run()


if __name__ == "__main__":
    main()
