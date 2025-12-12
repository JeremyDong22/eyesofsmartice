#!/usr/bin/env python3
"""
Supabase Sync Manager - Database-Only Cloud Sync
Version: 1.0.0
Created: 2025-11-15

Purpose:
- Sync local SQLite database to Supabase PostgreSQL cloud
- Database records ONLY (no screenshots, no videos)
- Hourly batch uploads with network failure tolerance
- Track sync status and retry failed uploads

Sync Strategy:
- Local SQLite = 24-hour transactional buffer (fast writes during processing)
- Supabase = permanent cloud storage (business analytics)
- Hourly sync: Upload new records, delete synced local records older than 24h

Usage:
    # Hourly sync (run via cron)
    python3 sync_to_supabase.py --mode hourly

    # Full sync (catch-up after network outage)
    python3 sync_to_supabase.py --mode full

    # Dry run (test without uploading)
    python3 sync_to_supabase.py --mode hourly --dry-run

Environment Variables Required:
    SUPABASE_URL: Your Supabase project URL
    SUPABASE_ANON_KEY: Your Supabase anon/publishable key
"""

import os
import sys
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import time

# Add parent directory to path for imports
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Constants
DB_PATH = PROJECT_ROOT / "db" / "detection_data.db"
BATCH_SIZE = 1000  # Records per batch upload


class SupabaseSyncManager:
    """
    Sync local SQLite data to Supabase cloud database
    Version: 1.0.0

    Features:
    - Hourly batch uploads
    - Network failure tolerance with retry queue
    - Progress tracking in sync_status table
    - Duplicate prevention via synced_to_cloud flag
    - Database-only sync (no media files)
    """

    def __init__(self, dry_run: bool = False):
        """
        Initialize sync manager

        Args:
            dry_run: If True, don't actually upload (for testing)
        """
        self.dry_run = dry_run
        self.local_db = None
        self.supabase = None
        self.location_id = None

        # Statistics
        self.stats = {
            'division_states_synced': 0,
            'table_states_synced': 0,
            'sessions_synced': 0,
            'videos_synced': 0,
            'errors': 0
        }

    def connect(self):
        """Connect to local database and Supabase"""
        # Connect to local SQLite
        if not DB_PATH.exists():
            raise FileNotFoundError(f"Database not found: {DB_PATH}")

        self.local_db = sqlite3.connect(str(DB_PATH))
        self.local_db.row_factory = sqlite3.Row  # Enable dict-like access

        # Get location_id from database
        cursor = self.local_db.cursor()
        cursor.execute("SELECT location_id FROM locations LIMIT 1")
        row = cursor.fetchone()
        if row:
            self.location_id = row['location_id']
        else:
            raise ValueError("No location found in database. Run initialize_restaurant.py first.")

        print(f"📍 Location: {self.location_id}")

        # Connect to Supabase (if not dry run)
        if not self.dry_run:
            supabase_url = os.getenv('SUPABASE_URL')
            supabase_key = os.getenv('SUPABASE_ANON_KEY')

            if not supabase_url or not supabase_key:
                raise ValueError(
                    "Supabase credentials not found in environment.\n"
                    "Set SUPABASE_URL and SUPABASE_ANON_KEY environment variables."
                )

            try:
                from supabase import create_client
                self.supabase = create_client(supabase_url, supabase_key)
                print(f"☁️  Connected to Supabase: {supabase_url}")
            except ImportError:
                raise ImportError(
                    "Supabase client not installed.\n"
                    "Install with: pip install supabase"
                )
        else:
            print("🔧 DRY RUN MODE - No actual uploads")

    def sync_hourly(self):
        """
        Hourly sync: Upload records from last 2 hours

        Uses 2-hour window for overlap/safety margin
        """
        print("\n" + "=" * 70)
        print("⏰ Hourly Sync Mode")
        print("=" * 70 + "\n")

        cutoff_time = datetime.now() - timedelta(hours=2)
        print(f"Syncing records since: {cutoff_time.strftime('%Y-%m-%d %H:%M:%S')}\n")

        # Sync each table type
        self.sync_videos(cutoff_time)
        self.sync_sessions(cutoff_time)
        self.sync_division_states(cutoff_time)
        self.sync_table_states(cutoff_time)

        # Cleanup old synced records (older than 24h)
        self.cleanup_synced_data(retention_hours=24)

        # Log sync status
        self.log_sync_status('hourly')

        # Print summary
        self.print_summary()

    def sync_full(self):
        """
        Full sync: Upload all unsynced records

        Use after network outage or initial setup
        """
        print("\n" + "=" * 70)
        print("🔄 Full Sync Mode")
        print("=" * 70 + "\n")

        print("Syncing ALL unsynced records...\n")

        # Sync all unsynced records (no time filter)
        self.sync_videos()
        self.sync_sessions()
        self.sync_division_states()
        self.sync_table_states()

        # Log sync status
        self.log_sync_status('full')

        # Print summary
        self.print_summary()

    def sync_videos(self, cutoff_time: Optional[datetime] = None):
        """
        Sync video metadata to ASE_videos

        Args:
            cutoff_time: Only sync videos created after this time (None = all)
        """
        print("📹 Syncing video metadata...")

        cursor = self.local_db.cursor()

        # Build query
        query = '''
            SELECT video_id, camera_id, video_filename, video_date,
                   start_time, end_time, duration_seconds, file_size_bytes,
                   fps, resolution, is_processed, storage_location
            FROM videos
            WHERE 1=1
        '''
        params = []

        if cutoff_time:
            query += " AND created_at >= ?"
            params.append(cutoff_time)

        cursor.execute(query, params)
        videos = cursor.fetchall()

        if not videos:
            print("   No videos to sync\n")
            return

        # Upload in batches
        total_uploaded = self._upload_in_batches(
            records=videos,
            table_name='ASE_videos',
            transform_fn=self._transform_video
        )

        self.stats['videos_synced'] = total_uploaded
        print(f"   ✅ Synced {total_uploaded} videos\n")

    def sync_sessions(self, cutoff_time: Optional[datetime] = None):
        """Sync processing sessions to ASE_sessions"""
        print("🎬 Syncing sessions...")

        cursor = self.local_db.cursor()

        query = '''
            SELECT session_id, camera_id, video_id, location_id, config_file_path,
                   roi_version, start_time, end_time, total_frames, fps, resolution,
                   processing_status, processing_time_seconds, error_message
            FROM sessions
            WHERE 1=1
        '''
        params = []

        if cutoff_time:
            query += " AND created_at >= ?"
            params.append(cutoff_time)

        cursor.execute(query, params)
        sessions = cursor.fetchall()

        if not sessions:
            print("   No sessions to sync\n")
            return

        total_uploaded = self._upload_in_batches(
            records=sessions,
            table_name='ASE_sessions',
            transform_fn=self._transform_session
        )

        self.stats['sessions_synced'] = total_uploaded
        print(f"   ✅ Synced {total_uploaded} sessions\n")

    def sync_division_states(self, cutoff_time: Optional[datetime] = None):
        """Sync division state changes to ASE_division_states"""
        print("🔴🟡🟢 Syncing division states...")

        cursor = self.local_db.cursor()

        query = '''
            SELECT session_id, camera_id, location_id, frame_number,
                   timestamp_video, timestamp_recorded, state,
                   walking_area_waiters, service_area_waiters, total_staff
            FROM division_states
            WHERE synced_to_cloud = 0
        '''
        params = []

        if cutoff_time:
            query += " AND created_at >= ?"
            params.append(cutoff_time)

        cursor.execute(query, params)
        states = cursor.fetchall()

        if not states:
            print("   No division states to sync\n")
            return

        total_uploaded = self._upload_in_batches(
            records=states,
            table_name='ASE_division_states',
            transform_fn=self._transform_division_state,
            mark_synced_table='division_states'
        )

        self.stats['division_states_synced'] = total_uploaded
        print(f"   ✅ Synced {total_uploaded} division state changes\n")

    def sync_table_states(self, cutoff_time: Optional[datetime] = None):
        """Sync table state changes to ASE_table_states"""
        print("📊 Syncing table states...")

        cursor = self.local_db.cursor()

        query = '''
            SELECT session_id, camera_id, location_id, frame_number,
                   timestamp_video, timestamp_recorded, table_id, state,
                   customers_count, waiters_count
            FROM table_states
            WHERE synced_to_cloud = 0
        '''
        params = []

        if cutoff_time:
            query += " AND created_at >= ?"
            params.append(cutoff_time)

        cursor.execute(query, params)
        states = cursor.fetchall()

        if not states:
            print("   No table states to sync\n")
            return

        total_uploaded = self._upload_in_batches(
            records=states,
            table_name='ASE_table_states',
            transform_fn=self._transform_table_state,
            mark_synced_table='table_states'
        )

        self.stats['table_states_synced'] = total_uploaded
        print(f"   ✅ Synced {total_uploaded} table state changes\n")

    def _upload_in_batches(
        self,
        records: List[sqlite3.Row],
        table_name: str,
        transform_fn,
        mark_synced_table: Optional[str] = None
    ) -> int:
        """
        Upload records to Supabase in batches

        Args:
            records: List of SQLite Row objects
            table_name: Supabase table name (e.g., 'ASE_division_states')
            transform_fn: Function to transform SQLite row to Supabase dict
            mark_synced_table: Local table to mark as synced (optional)

        Returns:
            Number of records uploaded
        """
        if self.dry_run:
            print(f"   [DRY RUN] Would upload {len(records)} records to {table_name}")
            return len(records)

        total_uploaded = 0

        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i:i + BATCH_SIZE]

            # Transform records
            batch_dicts = [transform_fn(record) for record in batch]

            # Upload batch
            try:
                self.supabase.table(table_name).insert(batch_dicts).execute()

                # Mark as synced in local database
                if mark_synced_table:
                    self._mark_batch_synced(mark_synced_table, batch)

                total_uploaded += len(batch)
                print(f"   Uploaded {total_uploaded}/{len(records)}...")

            except Exception as e:
                print(f"   ❌ Upload failed for batch {i // BATCH_SIZE + 1}: {e}")
                self.stats['errors'] += 1
                # Continue with next batch instead of failing completely

        return total_uploaded

    def _mark_batch_synced(self, table_name: str, batch: List[sqlite3.Row]):
        """Mark uploaded records as synced in local database"""
        cursor = self.local_db.cursor()

        # Get primary key column name
        if table_name == 'division_states':
            pk_col = 'division_state_id'
        elif table_name == 'table_states':
            pk_col = 'table_state_id'
        else:
            return  # No synced_to_cloud column

        # Extract IDs from batch
        ids = [record[pk_col] for record in batch]

        # Update synced flag
        placeholders = ','.join('?' * len(ids))
        cursor.execute(f'''
            UPDATE {table_name}
            SET synced_to_cloud = 1
            WHERE {pk_col} IN ({placeholders})
        ''', ids)

        self.local_db.commit()

    def _transform_video(self, row: sqlite3.Row) -> Dict:
        """Transform SQLite video row to Supabase format"""
        return {
            'camera_id': row['camera_id'],
            'video_filename': row['video_filename'],
            'video_date': row['video_date'],
            'start_time': row['start_time'],
            'end_time': row['end_time'],
            'duration_seconds': row['duration_seconds'],
            'file_size_bytes': row['file_size_bytes'],
            'fps': row['fps'],
            'resolution': row['resolution'],
            'is_processed': bool(row['is_processed']),
            'storage_location': row['storage_location']
        }

    def _transform_session(self, row: sqlite3.Row) -> Dict:
        """Transform SQLite session row to Supabase format"""
        return {
            'session_id': row['session_id'],
            'camera_id': row['camera_id'],
            'video_id': row['video_id'],
            'location_id': row['location_id'],
            'config_file_path': row['config_file_path'],
            'roi_version': row['roi_version'],
            'start_time': row['start_time'],
            'end_time': row['end_time'],
            'total_frames': row['total_frames'],
            'fps': row['fps'],
            'resolution': row['resolution'],
            'processing_status': row['processing_status'],
            'processing_time_seconds': row['processing_time_seconds'],
            'error_message': row['error_message']
        }

    def _transform_division_state(self, row: sqlite3.Row) -> Dict:
        """Transform SQLite division state row to Supabase format"""
        return {
            'session_id': row['session_id'],
            'camera_id': row['camera_id'],
            'location_id': row['location_id'],
            'frame_number': row['frame_number'],
            'timestamp_video': row['timestamp_video'],
            'timestamp_recorded': row['timestamp_recorded'],
            'state': row['state'],
            'walking_area_waiters': row['walking_area_waiters'],
            'service_area_waiters': row['service_area_waiters'],
            'total_staff': row['total_staff']
        }

    def _transform_table_state(self, row: sqlite3.Row) -> Dict:
        """Transform SQLite table state row to Supabase format"""
        return {
            'session_id': row['session_id'],
            'camera_id': row['camera_id'],
            'location_id': row['location_id'],
            'frame_number': row['frame_number'],
            'timestamp_video': row['timestamp_video'],
            'timestamp_recorded': row['timestamp_recorded'],
            'table_id': row['table_id'],
            'state': row['state'],
            'customers_count': row['customers_count'],
            'waiters_count': row['waiters_count']
        }

    def cleanup_synced_data(self, retention_hours: int = 24):
        """
        Delete local records that have been synced and are older than retention period

        Args:
            retention_hours: Keep records for this many hours after sync (default: 24)
        """
        print(f"🗑️  Cleaning up synced data older than {retention_hours}h...")

        if self.dry_run:
            print("   [DRY RUN] Would delete old synced records\n")
            return

        cutoff_time = datetime.now() - timedelta(hours=retention_hours)
        cursor = self.local_db.cursor()

        # Delete old division states
        cursor.execute('''
            DELETE FROM division_states
            WHERE synced_to_cloud = 1
            AND created_at < ?
        ''', (cutoff_time,))
        deleted_division = cursor.rowcount

        # Delete old table states
        cursor.execute('''
            DELETE FROM table_states
            WHERE synced_to_cloud = 1
            AND created_at < ?
        ''', (cutoff_time,))
        deleted_table = cursor.rowcount

        self.local_db.commit()

        print(f"   Deleted {deleted_division} division states")
        print(f"   Deleted {deleted_table} table states\n")

    def log_sync_status(self, sync_type: str):
        """Log sync operation to sync_status table"""
        if self.dry_run:
            return

        cursor = self.local_db.cursor()

        total_synced = (
            self.stats['division_states_synced'] +
            self.stats['table_states_synced'] +
            self.stats['sessions_synced'] +
            self.stats['videos_synced']
        )

        status = 'success' if self.stats['errors'] == 0 else 'partial'
        error_msg = f"{self.stats['errors']} batch errors" if self.stats['errors'] > 0 else None

        cursor.execute('''
            INSERT INTO sync_status
            (location_id, sync_type, last_sync_time, records_synced, status, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            self.location_id,
            sync_type,
            datetime.now(),
            total_synced,
            status,
            error_msg
        ))

        self.local_db.commit()

    def print_summary(self):
        """Print sync summary"""
        print("=" * 70)
        print("📊 Sync Summary")
        print("=" * 70)
        print(f"Videos synced:         {self.stats['videos_synced']}")
        print(f"Sessions synced:       {self.stats['sessions_synced']}")
        print(f"Division states:       {self.stats['division_states_synced']}")
        print(f"Table states:          {self.stats['table_states_synced']}")
        print(f"Errors:                {self.stats['errors']}")
        print()

        if self.stats['errors'] == 0:
            print("✅ Sync completed successfully!")
        else:
            print(f"⚠️  Sync completed with {self.stats['errors']} errors")

        print()

    def close(self):
        """Close database connections"""
        if self.local_db:
            self.local_db.close()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Sync local database to Supabase cloud (database records only, no media)"
    )
    parser.add_argument(
        '--mode',
        choices=['hourly', 'full'],
        default='hourly',
        help='Sync mode: hourly (last 2h) or full (all unsynced)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Test mode - don\'t actually upload anything'
    )

    args = parser.parse_args()

    syncer = SupabaseSyncManager(dry_run=args.dry_run)

    try:
        syncer.connect()

        if args.mode == 'hourly':
            syncer.sync_hourly()
        else:
            syncer.sync_full()

    except Exception as e:
        print(f"\n❌ Sync failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        syncer.close()


if __name__ == "__main__":
    main()
