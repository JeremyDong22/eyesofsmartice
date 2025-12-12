#!/usr/bin/env python3
"""
Database Migration Script
Version: 1.0.0
Created: 2025-11-15

Purpose:
- Migrate existing detection_data.db to new v2.0.0 schema
- Add location_id and missing tables
- Backfill existing data with location/camera references
- Apply new schema without losing existing data

Usage:
    python3 migrate_database.py [--backup]

Options:
    --backup    Create backup before migration (recommended)
"""

import os
import sys
import sqlite3
import argparse
import shutil
from pathlib import Path
from datetime import datetime

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DB_PATH = PROJECT_ROOT / "db" / "detection_data.db"
SCHEMA_PATH = PROJECT_ROOT / "db" / "database_schema.sql"


class DatabaseMigrator:
    """
    Database migration from old schema to v2.0.0
    Version: 1.0.0
    """

    def __init__(self, db_path: Path, backup: bool = True):
        self.db_path = db_path
        self.backup = backup
        self.conn = None

    def run(self):
        """Execute migration"""
        print("=" * 70)
        print("🔄 Database Migration to v2.0.0")
        print("=" * 70)
        print()

        # Step 1: Backup
        if self.backup:
            self.create_backup()

        # Step 2: Connect
        self.connect_database()

        # Step 3: Check current schema
        self.analyze_current_schema()

        # Step 4: Apply new schema
        self.apply_new_schema()

        # Step 5: Backfill data
        self.backfill_data()

        # Step 6: Verify
        self.verify_migration()

        print("\n✅ Migration completed successfully!\n")

    def create_backup(self):
        """Create database backup"""
        print("💾 Step 1: Creating backup...")

        if not self.db_path.exists():
            print(f"   ⚠️  Database not found: {self.db_path}")
            print("   No backup needed (fresh installation)\n")
            return

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = self.db_path.parent / f"detection_data_backup_{timestamp}.db"

        shutil.copy2(self.db_path, backup_path)
        print(f"   ✅ Backup created: {backup_path.name}\n")

    def connect_database(self):
        """Connect to database"""
        print("🔌 Step 2: Connecting to database...")

        # Create db directory if doesn't exist
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(str(self.db_path))
        print(f"   ✅ Connected to: {self.db_path}\n")

    def analyze_current_schema(self):
        """Analyze current database schema"""
        print("🔍 Step 3: Analyzing current schema...")

        cursor = self.conn.cursor()

        # Get existing tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]

        print(f"   Current tables: {', '.join(tables) if tables else 'None'}")

        # Check for v2.0.0 indicators
        has_locations = 'locations' in tables
        has_cameras = 'cameras' in tables
        has_location_id = False

        if 'sessions' in tables:
            cursor.execute("PRAGMA table_info(sessions)")
            columns = [col[1] for col in cursor.fetchall()]
            has_location_id = 'location_id' in columns

        if has_locations and has_cameras and has_location_id:
            print("   ✅ Already on v2.0.0 schema\n")
        else:
            print("   ⚠️  Old schema detected, needs migration\n")

    def apply_new_schema(self):
        """Apply new schema from schema file"""
        print("📊 Step 4: Applying new schema...")

        if not SCHEMA_PATH.exists():
            print(f"   ❌ Schema file not found: {SCHEMA_PATH}")
            print("   Creating basic schema...\n")
            self._create_basic_schema()
            return

        # Load schema file
        with open(SCHEMA_PATH, 'r') as f:
            schema_sql = f.read()

        # Execute schema (CREATE IF NOT EXISTS = safe)
        self.conn.executescript(schema_sql)
        self.conn.commit()

        print(f"   ✅ Schema applied from {SCHEMA_PATH.name}\n")

    def _create_basic_schema(self):
        """Create basic v2.0.0 schema if file not found"""
        cursor = self.conn.cursor()

        # Locations table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS locations (
                location_id TEXT PRIMARY KEY,
                city TEXT NOT NULL,
                restaurant_name TEXT NOT NULL,
                commercial_area TEXT NOT NULL,
                address TEXT,
                region TEXT,
                timezone TEXT DEFAULT 'Asia/Shanghai',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
        ''')

        # Cameras table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cameras (
                camera_id TEXT PRIMARY KEY,
                location_id TEXT NOT NULL,
                camera_name TEXT,
                camera_ip_address TEXT NOT NULL,
                rtsp_endpoint TEXT,
                camera_type TEXT DEFAULT 'UNV',
                resolution TEXT,
                division_name TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (location_id) REFERENCES locations(location_id)
            )
        ''')

        # Update existing tables to add location_id
        self._add_location_id_columns()

        self.conn.commit()

    def _add_location_id_columns(self):
        """Add location_id columns to existing tables if missing"""
        cursor = self.conn.cursor()

        # Tables that need location_id
        tables_to_update = ['sessions', 'division_states', 'table_states']

        for table in tables_to_update:
            # Check if table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            )
            if not cursor.fetchone():
                continue  # Table doesn't exist yet

            # Check if location_id column exists
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [col[1] for col in cursor.fetchall()]

            if 'location_id' not in columns:
                print(f"   Adding location_id to {table}...")
                cursor.execute(f'''
                    ALTER TABLE {table}
                    ADD COLUMN location_id TEXT
                ''')

    def backfill_data(self):
        """Backfill existing data with location/camera references"""
        print("🔧 Step 5: Backfilling data...")

        cursor = self.conn.cursor()

        # Check if any location exists
        cursor.execute("SELECT COUNT(*) FROM locations")
        location_count = cursor.fetchone()[0]

        if location_count == 0:
            print("   ⚠️  No location found. Run initialize_restaurant.py to set up location.")
            print("   Skipping backfill (no data to migrate)\n")
            return

        # Get default location_id
        cursor.execute("SELECT location_id FROM locations LIMIT 1")
        default_location_id = cursor.fetchone()[0]

        print(f"   Using default location: {default_location_id}")

        # Backfill sessions
        cursor.execute("UPDATE sessions SET location_id = ? WHERE location_id IS NULL", (default_location_id,))
        sessions_updated = cursor.rowcount

        # Backfill division_states
        cursor.execute("UPDATE division_states SET location_id = ? WHERE location_id IS NULL", (default_location_id,))
        division_updated = cursor.rowcount

        # Backfill table_states
        cursor.execute("UPDATE table_states SET location_id = ? WHERE location_id IS NULL", (default_location_id,))
        table_updated = cursor.rowcount

        self.conn.commit()

        print(f"   Updated {sessions_updated} sessions")
        print(f"   Updated {division_updated} division states")
        print(f"   Updated {table_updated} table states\n")

    def verify_migration(self):
        """Verify migration was successful"""
        print("✅ Step 6: Verifying migration...")

        cursor = self.conn.cursor()

        # Check all required tables exist
        required_tables = [
            'locations', 'cameras', 'sessions',
            'division_states', 'table_states',
            'sync_queue', 'sync_status'
        ]

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        existing_tables = [row[0] for row in cursor.fetchall()]

        missing_tables = set(required_tables) - set(existing_tables)

        if missing_tables:
            print(f"   ⚠️  Missing tables: {', '.join(missing_tables)}")
            print("   Migration may be incomplete\n")
            return False

        # Check location_id columns exist
        for table in ['sessions', 'division_states', 'table_states']:
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [col[1] for col in cursor.fetchall()]

            if 'location_id' not in columns:
                print(f"   ❌ {table} missing location_id column")
                return False

        # Check synced_to_cloud columns
        for table in ['division_states', 'table_states']:
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [col[1] for col in cursor.fetchall()]

            if 'synced_to_cloud' not in columns:
                print(f"   ⚠️  {table} missing synced_to_cloud column (will be added)")
                cursor.execute(f'''
                    ALTER TABLE {table}
                    ADD COLUMN synced_to_cloud INTEGER DEFAULT 0
                ''')

        self.conn.commit()

        print("   ✅ All required tables and columns present")
        print("   ✅ Schema version: 2.0.0\n")

        return True

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Migrate database to v2.0.0 schema"
    )
    parser.add_argument(
        '--backup',
        action='store_true',
        default=True,
        help='Create backup before migration (default: True)'
    )
    parser.add_argument(
        '--no-backup',
        dest='backup',
        action='store_false',
        help='Skip backup creation (not recommended)'
    )

    args = parser.parse_args()

    migrator = DatabaseMigrator(DB_PATH, backup=args.backup)

    try:
        migrator.run()

        print("Next Steps:")
        print("  1. If no location exists, run: python3 scripts/deployment/initialize_restaurant.py")
        print("  2. Test video processing with new schema")
        print("  3. Set up Supabase sync: python3 scripts/database_sync/sync_to_supabase.py --dry-run")
        print()

    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        migrator.close()


if __name__ == "__main__":
    main()
