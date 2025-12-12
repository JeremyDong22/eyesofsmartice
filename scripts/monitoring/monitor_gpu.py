#!/usr/bin/env python3
"""
GPU Health Monitor
Version: 1.0.0
Last Updated: 2025-11-14

Purpose: Monitor NVIDIA GPU temperature, utilization, and memory

Usage:
  python3 monitor_gpu.py              # One-time check
  python3 monitor_gpu.py --watch 30   # Watch every 30 seconds
  python3 monitor_gpu.py --alert 80   # Alert if temp > 80°C
"""

import subprocess
import sys
import time
import argparse
from datetime import datetime

def check_nvidia_smi():
    """Check if nvidia-smi is available"""
    try:
        result = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

def get_gpu_stats():
    """Get GPU statistics"""
    if not check_nvidia_smi():
        return None

    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total,name",
                "--format=csv,noheader,nounits"
            ],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            temp, util, mem_used, mem_total, name = result.stdout.strip().split(", ")
            return {
                'temperature': int(temp),
                'utilization': int(util),
                'memory_used': int(mem_used),
                'memory_total': int(mem_total),
                'memory_percent': (int(mem_used) / int(mem_total)) * 100,
                'name': name
            }
    except Exception as e:
        print(f"Error querying GPU: {e}")

    return None

def print_gpu_status(stats, temp_threshold=80):
    """Print GPU status with color coding"""
    if stats is None:
        print("❌ GPU not available (nvidia-smi not found)")
        return 2

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    temp = stats['temperature']
    util = stats['utilization']
    mem_pct = stats['memory_percent']

    # Status indicators
    if temp >= temp_threshold:
        temp_status = "🔥 HOT"
        exit_code = 1
    elif temp >= temp_threshold - 10:
        temp_status = "⚠️  WARM"
        exit_code = 0
    else:
        temp_status = "✅ COOL"
        exit_code = 0

    print(f"\n[{timestamp}]")
    print(f"GPU: {stats['name']}")
    print(f"Temperature:  {temp}°C {temp_status}")
    print(f"Utilization:  {util}%")
    print(f"Memory:       {stats['memory_used']}MB / {stats['memory_total']}MB ({mem_pct:.1f}%)")

    return exit_code

def main():
    parser = argparse.ArgumentParser(description="Monitor GPU health")
    parser.add_argument("--watch", type=int, metavar="SECONDS",
                       help="Watch mode: update every N seconds")
    parser.add_argument("--alert", type=int, default=80,
                       help="Temperature alert threshold (default: 80°C)")

    args = parser.parse_args()

    if args.watch:
        print(f"Watching GPU (updating every {args.watch}s, Ctrl+C to stop)...")
        try:
            while True:
                stats = get_gpu_stats()
                print_gpu_status(stats, args.alert)
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\n\nStopped monitoring")
            sys.exit(0)
    else:
        stats = get_gpu_stats()
        exit_code = print_gpu_status(stats, args.alert)
        sys.exit(exit_code)

if __name__ == "__main__":
    main()
