#!/usr/bin/env python3
"""
Scale ROI Configuration for Different Resolutions
Version: 1.0.0
Created: 2025-11-23

This script scales ROI configurations from one resolution to another.
Used when configuration was created with a test video at different resolution
than the production camera feed.

Problem: Configuration created at 1920x1080, production camera at 2592x1944
Solution: Scale all polygon coordinates proportionally
"""

import json
import os
import sys
import argparse
from pathlib import Path
import shutil
from datetime import datetime


def scale_polygon(polygon, scale_x, scale_y):
    """Scale polygon coordinates by given factors"""
    return [[int(x * scale_x), int(y * scale_y)] for x, y in polygon]


def scale_config(config_path, target_width, target_height, backup=True):
    """
    Scale ROI configuration to target resolution

    Args:
        config_path: Path to configuration file
        target_width: Target frame width
        target_height: Target frame height
        backup: Whether to create backup of original file
    """
    # Load configuration
    with open(config_path, 'r') as f:
        config = json.load(f)

    # Get original frame size
    original_width, original_height = config.get('frame_size', [1920, 1080])

    # Calculate scaling factors
    scale_x = target_width / original_width
    scale_y = target_height / original_height

    print(f"📊 Scaling Configuration:")
    print(f"   Original: {original_width}x{original_height}")
    print(f"   Target:   {target_width}x{target_height}")
    print(f"   Scale:    {scale_x:.3f}x (width), {scale_y:.3f}x (height)")

    # Create backup if requested
    if backup:
        backup_path = config_path.replace('.json', f'_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
        shutil.copy2(config_path, backup_path)
        print(f"✅ Backup created: {backup_path}")

    # Scale division polygon
    if 'division' in config:
        config['division'] = scale_polygon(config['division'], scale_x, scale_y)
        print(f"   Scaled division boundary ({len(config['division'])} points)")

    # Scale tables
    if 'tables' in config:
        for table in config['tables']:
            table['polygon'] = scale_polygon(table['polygon'], scale_x, scale_y)
        print(f"   Scaled {len(config['tables'])} tables")

    # Scale sitting areas
    if 'sitting_areas' in config:
        for area in config['sitting_areas']:
            area['polygon'] = scale_polygon(area['polygon'], scale_x, scale_y)
        print(f"   Scaled {len(config['sitting_areas'])} sitting areas")

    # Scale service areas
    if 'service_areas' in config:
        for area in config['service_areas']:
            area['polygon'] = scale_polygon(area['polygon'], scale_x, scale_y)
        print(f"   Scaled {len(config['service_areas'])} service areas")

    # Update frame size
    config['frame_size'] = [target_width, target_height]

    # Save scaled configuration
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"✅ Configuration scaled and saved to: {config_path}")
    return config


def main():
    parser = argparse.ArgumentParser(
        description='Scale ROI configuration to different resolution',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scale to production camera resolution (2592x1944)
  python3 scale_roi_config.py --width 2592 --height 1944

  # Scale specific config file
  python3 scale_roi_config.py --config ../config/camera_35_roi.json --width 2592 --height 1944

  # Scale without backup
  python3 scale_roi_config.py --width 2592 --height 1944 --no-backup

  # Scale all config files in directory
  python3 scale_roi_config.py --width 2592 --height 1944 --all
        """
    )

    parser.add_argument('--config', type=str,
                        help='Path to configuration file (default: auto-detect)')
    parser.add_argument('--width', type=int, required=True,
                        help='Target frame width')
    parser.add_argument('--height', type=int, required=True,
                        help='Target frame height')
    parser.add_argument('--no-backup', action='store_true',
                        help='Do not create backup of original file')
    parser.add_argument('--all', action='store_true',
                        help='Scale all config files in config directory')

    args = parser.parse_args()

    # Determine config files to process
    config_dir = Path(__file__).parent.parent / 'config'

    if args.all:
        # Process all ROI config files
        config_files = [
            config_dir / 'table_region_config.json',
            config_dir / 'camera_35_roi.json'
        ]
        config_files = [f for f in config_files if f.exists()]
    elif args.config:
        config_files = [Path(args.config)]
    else:
        # Auto-detect config files
        config_files = []
        if (config_dir / 'table_region_config.json').exists():
            config_files.append(config_dir / 'table_region_config.json')
        if (config_dir / 'camera_35_roi.json').exists():
            config_files.append(config_dir / 'camera_35_roi.json')

    if not config_files:
        print("❌ No configuration files found!")
        print(f"   Searched in: {config_dir}")
        sys.exit(1)

    # Process each config file
    for config_path in config_files:
        print(f"\n🔧 Processing: {config_path.name}")
        print("=" * 60)

        try:
            scale_config(
                str(config_path),
                args.width,
                args.height,
                backup=not args.no_backup
            )
        except Exception as e:
            print(f"❌ Error processing {config_path.name}: {e}")
            continue

    print("\n✨ Scaling complete!")
    print("\nNext steps:")
    print("1. Copy scaled configs to Linux RTX machine:")
    print("   scp scripts/config/*.json user@rtx-machine:/path/to/production/RTX_3060/scripts/config/")
    print("2. Test with production camera feed")
    print("3. If needed, use interactive mode to fine-tune")


if __name__ == '__main__':
    main()