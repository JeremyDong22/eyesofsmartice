#!/usr/bin/env bash
################################################################################
# RTX 3060 Production System - One-Time Initialization Master Script
# Version: 1.0.0
# Last Updated: 2025-11-14
#
# Purpose: Interactive deployment wizard for restaurant surveillance system
# Handles camera setup, ROI configuration, prerequisite validation, and
# readiness verification for production deployment
#
# Usage:
#   chmod +x initialize_deployment.sh
#   ./initialize_deployment.sh
#
# Author: ASEOfSmartICE Team
################################################################################

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Script paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_ROOT="$(dirname "$SCRIPT_DIR")"
PARENT_DIR="$(dirname "$SCRIPTS_ROOT")"
CAMERAS_CONFIG="$SCRIPTS_ROOT/config/cameras_config.json"
CAMERAS_CONFIG_BACKUP="$SCRIPTS_ROOT/config/cameras_config.json.backup"
ROI_CONFIG="$SCRIPTS_ROOT/config/table_region_config.json"
ROI_CONFIG_BACKUP="$SCRIPTS_ROOT/config/table_region_config.json.backup"
TEST_SCRIPT="$SCRIPTS_ROOT/camera_testing/test_camera_connections.py"
ROI_SCRIPT="$SCRIPTS_ROOT/video_processing/table_and_region_state_detection.py"

# Track deployment state
CAMERAS_CONFIGURED=false
ROI_CONFIGURED=false
DEPLOYMENT_READY=false

################################################################################
# Utility Functions
################################################################################

print_header() {
    echo ""
    echo -e "${CYAN}================================================================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}================================================================================${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

print_step() {
    echo -e "${MAGENTA}▶ $1${NC}"
}

confirm_action() {
    local prompt="$1"
    local default="${2:-n}"

    if [[ "$default" == "y" ]]; then
        read -p "$(echo -e ${YELLOW}${prompt} [Y/n]: ${NC})" -n 1 -r
    else
        read -p "$(echo -e ${YELLOW}${prompt} [y/N]: ${NC})" -n 1 -r
    fi
    echo

    if [[ "$default" == "y" ]]; then
        [[ $REPLY =~ ^[Nn]$ ]] && return 1 || return 0
    else
        [[ $REPLY =~ ^[Yy]$ ]] && return 0 || return 1
    fi
}

validate_ip() {
    local ip=$1
    if [[ $ip =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
        IFS='.' read -ra ADDR <<< "$ip"
        [[ ${ADDR[0]} -le 255 && ${ADDR[1]} -le 255 && ${ADDR[2]} -le 255 && ${ADDR[3]} -le 255 ]]
        return $?
    else
        return 1
    fi
}

backup_file() {
    local file=$1
    local backup=$2

    if [[ -f "$file" ]]; then
        print_info "Backing up existing configuration: $file"
        cp "$file" "$backup"
        print_success "Backup created: $backup"
    fi
}

create_directories() {
    print_step "Creating necessary directories..."

    local dirs=(
        "$PARENT_DIR/videos"
        "$PARENT_DIR/results"
        "$PARENT_DIR/db"
        "$PARENT_DIR/db/screenshots"
        "$PARENT_DIR/tests/camera_test_videos"
        "$PARENT_DIR/tests/camera_test_reports"
    )

    for dir in "${dirs[@]}"; do
        if [[ ! -d "$dir" ]]; then
            mkdir -p "$dir"
            print_success "Created: $dir"
        else
            print_info "Already exists: $dir"
        fi
    done
}

set_permissions() {
    print_step "Setting script permissions..."

    local scripts=(
        "$SCRIPTS_ROOT/camera_testing/test_camera_connections.py"
        "$SCRIPTS_ROOT/video_processing/table_and_region_state_detection.py"
        "$SCRIPTS_ROOT/video_capture/capture_rtsp_streams.py"
        "$SCRIPTS_ROOT/orchestration/process_videos_orchestrator.py"
        "$SCRIPTS_ROOT/time_sync/setup_ntp.sh"
        "$SCRIPTS_ROOT/time_sync/verify_time_sync.sh"
        "$SCRIPTS_ROOT/maintenance/cleanup_old_videos.sh"
        "$SCRIPTS_ROOT/run_interactive.sh"
        "$SCRIPTS_ROOT/run_with_config.sh"
        "$SCRIPTS_ROOT/camera_testing/run_camera_test.sh"
        "$SCRIPTS_ROOT/camera_testing/quick_camera_test.sh"
    )

    for script in "${scripts[@]}"; do
        if [[ -f "$script" ]]; then
            chmod +x "$script"
            print_success "Set executable: $(basename "$script")"
        fi
    done
}

################################################################################
# Prerequisite Checks
################################################################################

check_prerequisites() {
    print_header "STEP 1: Checking Prerequisites"

    local all_good=true

    # Check Python 3
    print_step "Checking Python 3..."
    if command -v python3 &> /dev/null; then
        local py_version=$(python3 --version)
        print_success "Found: $py_version"
    else
        print_error "Python 3 not found"
        all_good=false
    fi

    # Check pip/packages
    print_step "Checking Python packages..."
    local packages=("cv2:opencv-python" "ultralytics" "numpy")
    for pkg_check in "${packages[@]}"; do
        IFS=':' read -r import_name package_name <<< "$pkg_check"
        package_name=${package_name:-$import_name}

        if python3 -c "import $import_name" 2>/dev/null; then
            print_success "Package installed: $package_name"
        else
            print_error "Package missing: $package_name"
            print_info "Install with: pip3 install $package_name"
            all_good=false
        fi
    done

    # Check ffmpeg
    print_step "Checking ffmpeg..."
    if command -v ffmpeg &> /dev/null; then
        local ff_version=$(ffmpeg -version | head -n 1)
        print_success "Found: $ff_version"
    else
        print_warning "ffmpeg not found (optional, improves video encoding)"
        print_info "Install with: sudo apt install ffmpeg (Linux) or brew install ffmpeg (macOS)"
    fi

    # Check ffprobe
    print_step "Checking ffprobe..."
    if command -v ffprobe &> /dev/null; then
        print_success "Found: ffprobe"
    else
        print_warning "ffprobe not found (optional, for video integrity checks)"
    fi

    # Check NVIDIA GPU (Linux only)
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        print_step "Checking NVIDIA GPU..."
        if command -v nvidia-smi &> /dev/null; then
            local gpu_info=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -n 1)
            print_success "Found: $gpu_info"

            # Check GPU utilization
            local gpu_util=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits | head -n 1)
            print_info "Current GPU utilization: ${gpu_util}%"
        else
            print_error "nvidia-smi not found (NVIDIA drivers not installed?)"
            all_good=false
        fi
    else
        print_warning "Not Linux - skipping GPU checks (development mode)"
    fi

    # Check models
    print_step "Checking YOLO models..."
    if [[ -f "$PARENT_DIR/models/yolov8m.pt" ]]; then
        local model_size=$(du -h "$PARENT_DIR/models/yolov8m.pt" | cut -f1)
        print_success "Found person detector: yolov8m.pt ($model_size)"
    else
        print_error "Missing: models/yolov8m.pt"
        all_good=false
    fi

    if [[ -f "$PARENT_DIR/models/waiter_customer_classifier.pt" ]]; then
        local model_size=$(du -h "$PARENT_DIR/models/waiter_customer_classifier.pt" | cut -f1)
        print_success "Found staff classifier: waiter_customer_classifier.pt ($model_size)"
    else
        print_error "Missing: models/waiter_customer_classifier.pt"
        all_good=false
    fi

    # Check disk space
    print_step "Checking disk space..."
    if python3 "$SCRIPTS_ROOT/monitoring/check_disk_space.py" --check; then
        print_success "Sufficient disk space available"
    else
        print_warning "Disk space may be insufficient"
        print_info "Run: python3 $SCRIPTS_ROOT/monitoring/check_disk_space.py --cleanup"
    fi

    echo ""
    if $all_good; then
        print_success "All prerequisites satisfied"
        return 0
    else
        print_error "Some prerequisites not met - please resolve before continuing"
        if ! confirm_action "Continue anyway?"; then
            exit 1
        fi
    fi
}

################################################################################
# Camera Configuration
################################################################################

configure_cameras() {
    print_header "STEP 2: Camera Configuration"

    # Check if config exists
    if [[ -f "$CAMERAS_CONFIG" ]]; then
        print_warning "Existing cameras_config.json found"
        cat "$CAMERAS_CONFIG"
        echo ""

        if confirm_action "Use existing configuration?"; then
            print_info "Using existing camera configuration"
            CAMERAS_CONFIGURED=true
            return 0
        else
            backup_file "$CAMERAS_CONFIG" "$CAMERAS_CONFIG_BACKUP"
        fi
    fi

    # Gather camera IPs
    print_step "Enter camera IPs (one per line, press Enter on empty line to finish)"
    print_info "You can configure 1-10 cameras"

    local camera_ips=()
    local ip_count=0

    while [[ $ip_count -lt 10 ]]; do
        read -p "Camera $((ip_count + 1)) IP: " ip

        # Empty input = done
        if [[ -z "$ip" ]]; then
            if [[ $ip_count -eq 0 ]]; then
                print_warning "At least one camera IP required"
                continue
            else
                break
            fi
        fi

        # Validate IP
        if validate_ip "$ip"; then
            camera_ips+=("$ip")
            print_success "Added: $ip"
            ip_count=$((ip_count + 1))
        else
            print_error "Invalid IP format: $ip"
            print_info "Expected format: XXX.XXX.XXX.XXX"
        fi
    done

    echo ""
    print_info "Collected ${#camera_ips[@]} camera IP(s)"

    # Gather credentials
    print_step "Enter camera credentials (press Enter for defaults)"
    read -p "Username [admin]: " camera_user
    camera_user=${camera_user:-admin}

    read -sp "Password [123456]: " camera_pass
    echo
    camera_pass=${camera_pass:-123456}

    print_success "Credentials set: $camera_user / ********"

    # Test connections
    echo ""
    print_step "Testing camera connections..."
    print_warning "This will take ~60 seconds per camera (includes 30s recording test)"

    if ! confirm_action "Proceed with connection tests?" "y"; then
        print_warning "Skipping connection tests"
        return 1
    fi

    # Build IP arguments
    local ip_args=""
    for ip in "${camera_ips[@]}"; do
        ip_args="$ip_args $ip"
    done

    # Run test script
    print_info "Running test_camera_connections.py..."
    if python3 "$TEST_SCRIPT" --ips $ip_args; then
        print_success "Camera testing completed"

        # Parse results
        echo ""
        print_header "Test Results Summary"

        if [[ -f "$CAMERAS_CONFIG" ]]; then
            local total_cameras=$(python3 -c "import json; data=json.load(open('$CAMERAS_CONFIG')); print(len(data))")
            local enabled_cameras=$(python3 -c "import json; data=json.load(open('$CAMERAS_CONFIG')); print(sum(1 for c in data.values() if c.get('enabled', False)))")
            local disabled_cameras=$((total_cameras - enabled_cameras))

            print_success "Total cameras: $total_cameras"
            print_success "Passed: $enabled_cameras"
            if [[ $disabled_cameras -gt 0 ]]; then
                print_warning "Failed: $disabled_cameras"
            fi

            # Show camera table
            echo ""
            print_info "Camera Configuration:"
            python3 -c "
import json
data = json.load(open('$CAMERAS_CONFIG'))
print(f\"{'Camera ID':<15} {'IP':<20} {'Resolution':<15} {'FPS':<8} {'Status':<10}\")
print('-' * 75)
for cam_id, cam in sorted(data.items()):
    ip = cam['ip']
    res = f\"{cam['resolution'][0]}x{cam['resolution'][1]}\"
    fps = cam.get('fps', 20)
    status = 'ENABLED' if cam.get('enabled') else 'DISABLED'
    print(f\"{cam_id:<15} {ip:<20} {res:<15} {fps:<8} {status:<10}\")
"

            CAMERAS_CONFIGURED=true
            print_success "Camera configuration complete"
            return 0
        else
            print_error "cameras_config.json not generated"
            return 1
        fi
    else
        print_error "Camera testing failed"
        return 1
    fi
}

################################################################################
# ROI Configuration
################################################################################

configure_roi() {
    print_header "STEP 3: ROI (Region of Interest) Configuration"

    if ! $CAMERAS_CONFIGURED; then
        print_error "Cameras must be configured before ROI setup"
        return 1
    fi

    # Check if ROI config exists
    if [[ -f "$ROI_CONFIG" ]]; then
        print_warning "Existing table_region_config.json found"

        # Show config summary
        if python3 -c "import json; json.load(open('$ROI_CONFIG'))" 2>/dev/null; then
            local table_count=$(python3 -c "import json; data=json.load(open('$ROI_CONFIG')); print(len(data.get('tables', [])))")
            local service_count=$(python3 -c "import json; data=json.load(open('$ROI_CONFIG')); print(len(data.get('service_areas', [])))")

            print_info "Current configuration: $table_count tables, $service_count service areas"

            if confirm_action "Use existing ROI configuration?"; then
                print_info "Using existing ROI configuration"
                ROI_CONFIGURED=true
                return 0
            else
                backup_file "$ROI_CONFIG" "$ROI_CONFIG_BACKUP"
            fi
        fi
    fi

    print_info "ROI setup requires running interactive mode per camera"
    print_info "You will draw regions on actual camera footage/recordings"
    echo ""
    print_step "Available cameras for ROI setup:"

    # List enabled cameras
    local enabled_ips=()
    if [[ -f "$CAMERAS_CONFIG" ]]; then
        mapfile -t enabled_ips < <(python3 -c "
import json
data = json.load(open('$CAMERAS_CONFIG'))
for cam in data.values():
    if cam.get('enabled'):
        print(cam['ip'])
" | sort)

        for i in "${!enabled_ips[@]}"; do
            echo "  $((i + 1)). ${enabled_ips[$i]}"
        done
    fi

    echo ""
    if [[ ${#enabled_ips[@]} -eq 0 ]]; then
        print_error "No enabled cameras found"
        return 1
    fi

    if ! confirm_action "Run interactive ROI setup for each camera?" "y"; then
        print_warning "Skipping ROI setup"
        print_info "You can run it later with: ./run_interactive.sh"
        return 1
    fi

    # Check for video files
    print_step "Checking for video files in ../videos/..."
    local video_files=()
    if [[ -d "$PARENT_DIR/videos" ]]; then
        mapfile -t video_files < <(find "$PARENT_DIR/videos" -name "*.mp4" -type f | sort)
    fi

    if [[ ${#video_files[@]} -eq 0 ]]; then
        print_warning "No video files found in ../videos/"
        print_info "You need video footage for ROI setup"
        print_info "Options:"
        print_info "  1. Record live streams: cd $SCRIPTS_ROOT && python3 video_capture/capture_rtsp_streams.py"
        print_info "  2. Use test recordings from camera tests"

        if [[ -d "$PARENT_DIR/tests/camera_test_videos" ]]; then
            local test_count=$(find "$PARENT_DIR/tests/camera_test_videos" -name "*.mp4" | wc -l)
            if [[ $test_count -gt 0 ]]; then
                print_info "Found $test_count test video(s) in tests/camera_test_videos/"
                if confirm_action "Copy test videos to videos/ folder?"; then
                    cp "$PARENT_DIR/tests/camera_test_videos"/*.mp4 "$PARENT_DIR/videos/" 2>/dev/null || true
                    print_success "Test videos copied"
                    mapfile -t video_files < <(find "$PARENT_DIR/videos" -name "*.mp4" -type f | sort)
                fi
            fi
        fi
    fi

    if [[ ${#video_files[@]} -eq 0 ]]; then
        print_error "No video files available for ROI setup"
        print_info "Please record some footage first, then run this script again"
        return 1
    fi

    # Show available videos
    print_success "Found ${#video_files[@]} video file(s)"
    for i in "${!video_files[@]}"; do
        local filename=$(basename "${video_files[$i]}")
        local filesize=$(du -h "${video_files[$i]}" | cut -f1)
        echo "  $((i + 1)). $filename ($filesize)"
    done

    echo ""
    read -p "Select video file number for ROI setup [1]: " video_choice
    video_choice=${video_choice:-1}

    if [[ $video_choice -lt 1 || $video_choice -gt ${#video_files[@]} ]]; then
        print_error "Invalid selection"
        return 1
    fi

    local selected_video="${video_files[$((video_choice - 1))]}"
    print_success "Selected: $(basename "$selected_video")"

    # Run interactive ROI setup
    echo ""
    print_header "Interactive ROI Setup"
    print_info "Instructions:"
    print_info "  1. Draw Division boundary (overall monitored area)"
    print_info "  2. For each table: Draw table surface → Draw sitting areas → Press 'D'"
    print_info "  3. Draw Service Areas (bar, POS, prep stations)"
    print_info "  4. Press Ctrl+S to save configuration"
    print_info ""
    print_info "Keyboard shortcuts:"
    print_info "  Enter       - Complete current ROI polygon"
    print_info "  D           - Finish current table, move to next"
    print_info "  S           - Skip remaining tables, go to Service Areas"
    print_info "  Ctrl+Z / U  - Undo last point/ROI"
    print_info "  Ctrl+S      - Save all configurations"
    print_info "  Q           - Quit"
    echo ""

    if ! confirm_action "Ready to start interactive ROI setup?" "y"; then
        print_warning "ROI setup cancelled"
        return 1
    fi

    # Run interactive mode
    print_step "Launching interactive ROI setup..."
    if python3 "$ROI_SCRIPT" --video "$selected_video" --interactive; then
        print_success "ROI configuration saved"

        # Verify config was created
        if [[ -f "$ROI_CONFIG" ]]; then
            local table_count=$(python3 -c "import json; data=json.load(open('$ROI_CONFIG')); print(len(data.get('tables', [])))")
            local service_count=$(python3 -c "import json; data=json.load(open('$ROI_CONFIG')); print(len(data.get('service_areas', [])))")

            print_success "Configuration created: $table_count tables, $service_count service areas"
            ROI_CONFIGURED=true
            return 0
        else
            print_error "ROI configuration file not created"
            return 1
        fi
    else
        print_error "ROI setup failed or cancelled"
        return 1
    fi
}

################################################################################
# System Verification
################################################################################

verify_system() {
    print_header "STEP 4: System Verification"

    local all_checks_passed=true

    # Check directory structure
    print_step "Verifying directory structure..."
    local dirs=("videos" "results" "db" "db/screenshots" "models" "scripts")
    for dir in "${dirs[@]}"; do
        if [[ -d "$PARENT_DIR/$dir" ]]; then
            print_success "Directory exists: $dir/"
        else
            print_error "Missing directory: $dir/"
            all_checks_passed=false
        fi
    done

    # Check models
    print_step "Verifying YOLO models..."
    if [[ -f "$PARENT_DIR/models/yolov8m.pt" ]]; then
        print_success "Person detector present"
    else
        print_error "Missing: yolov8m.pt"
        all_checks_passed=false
    fi

    if [[ -f "$PARENT_DIR/models/waiter_customer_classifier.pt" ]]; then
        print_success "Staff classifier present"
    else
        print_error "Missing: waiter_customer_classifier.pt"
        all_checks_passed=false
    fi

    # Check configurations
    print_step "Verifying configurations..."
    if [[ -f "$CAMERAS_CONFIG" ]]; then
        if python3 -c "import json; json.load(open('$CAMERAS_CONFIG'))" 2>/dev/null; then
            print_success "cameras_config.json valid"
        else
            print_error "cameras_config.json invalid JSON"
            all_checks_passed=false
        fi
    else
        print_warning "cameras_config.json not found"
    fi

    if [[ -f "$ROI_CONFIG" ]]; then
        if python3 -c "import json; json.load(open('$ROI_CONFIG'))" 2>/dev/null; then
            print_success "table_region_config.json valid"
        else
            print_error "table_region_config.json invalid JSON"
            all_checks_passed=false
        fi
    else
        print_warning "table_region_config.json not found"
    fi

    # Check NTP sync (Linux only)
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        print_step "Checking NTP time synchronization..."
        if command -v timedatectl &> /dev/null; then
            if timedatectl status | grep -q "System clock synchronized: yes"; then
                print_success "NTP synchronized"
            else
                print_warning "NTP not synchronized"
                print_info "Run: sudo ./setup_ntp.sh"
            fi
        else
            print_warning "timedatectl not available (check NTP manually)"
        fi
    fi

    # Check database
    print_step "Verifying database setup..."
    if [[ -f "$PARENT_DIR/db/detection_data.db" ]]; then
        print_info "Existing database found"
        local session_count=$(sqlite3 "$PARENT_DIR/db/detection_data.db" "SELECT COUNT(*) FROM sessions" 2>/dev/null || echo "0")
        print_info "Database contains $session_count session(s)"
    else
        print_info "Database will be created on first run"
    fi

    # Check scripts are executable
    print_step "Verifying script permissions..."
    local key_scripts=(
        "$SCRIPTS_ROOT/camera_testing/test_camera_connections.py"
        "$SCRIPTS_ROOT/video_processing/table_and_region_state_detection.py"
        "$SCRIPTS_ROOT/video_capture/capture_rtsp_streams.py"
    )

    for script in "${key_scripts[@]}"; do
        if [[ -x "$script" ]]; then
            print_success "Executable: $(basename "$script")"
        else
            print_warning "Not executable: $(basename "$script")"
            chmod +x "$script" 2>/dev/null && print_success "Fixed permissions"
        fi
    done

    echo ""
    if $all_checks_passed; then
        print_success "All system checks passed"
        DEPLOYMENT_READY=true
        return 0
    else
        print_warning "Some checks failed - review errors above"
        DEPLOYMENT_READY=false
        return 1
    fi
}

################################################################################
# Deployment Readiness Report
################################################################################

show_deployment_report() {
    print_header "DEPLOYMENT READINESS CHECKLIST"

    # Prerequisites
    echo -e "${CYAN}Prerequisites:${NC}"
    if command -v python3 &> /dev/null; then
        print_success "Python 3 installed"
    else
        print_error "Python 3 missing"
    fi

    if python3 -c "import cv2, ultralytics, numpy" 2>/dev/null; then
        print_success "Required Python packages installed"
    else
        print_error "Missing Python packages"
    fi

    if [[ "$OSTYPE" == "linux-gnu"* ]] && command -v nvidia-smi &> /dev/null; then
        print_success "NVIDIA GPU drivers installed"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        print_error "NVIDIA GPU drivers not found"
    else
        print_warning "Not Linux (development mode)"
    fi

    # Directory structure
    echo ""
    echo -e "${CYAN}Directory Structure:${NC}"
    if [[ -d "$PARENT_DIR/videos" && -d "$PARENT_DIR/results" && -d "$PARENT_DIR/db" ]]; then
        print_success "All required directories present"
    else
        print_error "Missing required directories"
    fi

    # Models
    echo ""
    echo -e "${CYAN}YOLO Models:${NC}"
    if [[ -f "$PARENT_DIR/models/yolov8m.pt" ]]; then
        print_success "Person detector model present"
    else
        print_error "Person detector model missing"
    fi

    if [[ -f "$PARENT_DIR/models/waiter_customer_classifier.pt" ]]; then
        print_success "Staff classifier model present"
    else
        print_error "Staff classifier model missing"
    fi

    # Camera configuration
    echo ""
    echo -e "${CYAN}Camera Configuration:${NC}"
    if [[ -f "$CAMERAS_CONFIG" ]]; then
        local total=$(python3 -c "import json; print(len(json.load(open('$CAMERAS_CONFIG'))))" 2>/dev/null || echo "0")
        local enabled=$(python3 -c "import json; print(sum(1 for c in json.load(open('$CAMERAS_CONFIG')).values() if c.get('enabled')))" 2>/dev/null || echo "0")
        print_success "Camera config present: $enabled/$total cameras enabled"
    else
        print_error "Camera configuration missing"
    fi

    # ROI configuration
    echo ""
    echo -e "${CYAN}ROI Configuration:${NC}"
    if [[ -f "$ROI_CONFIG" ]]; then
        local tables=$(python3 -c "import json; print(len(json.load(open('$ROI_CONFIG')).get('tables', [])))" 2>/dev/null || echo "0")
        local services=$(python3 -c "import json; print(len(json.load(open('$ROI_CONFIG')).get('service_areas', [])))" 2>/dev/null || echo "0")
        print_success "ROI config present: $tables tables, $services service areas"
    else
        print_warning "ROI configuration missing (optional per camera)"
    fi

    # Time sync
    echo ""
    echo -e "${CYAN}Time Synchronization:${NC}"
    if [[ "$OSTYPE" == "linux-gnu"* ]] && command -v timedatectl &> /dev/null; then
        if timedatectl status | grep -q "System clock synchronized: yes"; then
            print_success "NTP synchronized"
        else
            print_warning "NTP not synchronized (run: sudo time_sync/setup_ntp.sh)"
        fi
    else
        print_warning "NTP check skipped (not Linux or timedatectl unavailable)"
    fi

    # Overall status
    echo ""
    echo -e "${CYAN}Overall Status:${NC}"
    if $DEPLOYMENT_READY && $CAMERAS_CONFIGURED; then
        print_success "System is ready for deployment"
        return 0
    else
        print_warning "System partially configured - review checklist above"
        return 1
    fi
}

################################################################################
# Test Recording
################################################################################

test_first_recording() {
    print_header "STEP 5: Test First Recording"

    if ! $DEPLOYMENT_READY; then
        print_warning "System not fully ready - skipping test recording"
        return 1
    fi

    print_info "Running a quick test to verify everything works"

    if ! confirm_action "Start test recording session?" "y"; then
        print_info "Test recording skipped"
        return 0
    fi

    # Check for video files
    local video_files=()
    if [[ -d "$PARENT_DIR/videos" ]]; then
        mapfile -t video_files < <(find "$PARENT_DIR/videos" -name "*.mp4" -type f | sort)
    fi

    if [[ ${#video_files[@]} -eq 0 ]]; then
        print_error "No video files found in ../videos/"
        print_info "Capture some footage first: cd $SCRIPTS_ROOT && python3 video_capture/capture_rtsp_streams.py"
        return 1
    fi

    # Select first video
    local test_video="${video_files[0]}"
    print_info "Using: $(basename "$test_video")"

    # Run detection for 60 seconds
    print_step "Running detection system (60 second test)..."
    if python3 "$ROI_SCRIPT" --video "$test_video" --duration 60; then
        print_success "Test recording completed successfully"

        # Check outputs
        echo ""
        print_info "Checking outputs..."

        # Check database
        if [[ -f "$PARENT_DIR/db/detection_data.db" ]]; then
            print_success "Database created/updated"
            local latest_session=$(sqlite3 "$PARENT_DIR/db/detection_data.db" "SELECT session_id FROM sessions ORDER BY start_time DESC LIMIT 1" 2>/dev/null)
            if [[ -n "$latest_session" ]]; then
                print_info "Latest session: $latest_session"

                # Count state changes
                local div_changes=$(sqlite3 "$PARENT_DIR/db/detection_data.db" "SELECT COUNT(*) FROM division_states WHERE session_id='$latest_session'" 2>/dev/null || echo "0")
                local table_changes=$(sqlite3 "$PARENT_DIR/db/detection_data.db" "SELECT COUNT(*) FROM table_states WHERE session_id='$latest_session'" 2>/dev/null || echo "0")
                print_info "State changes logged: $div_changes division, $table_changes table"
            fi
        fi

        # Check screenshots
        if [[ -d "$PARENT_DIR/db/screenshots" ]]; then
            local screenshot_count=$(find "$PARENT_DIR/db/screenshots" -name "*.jpg" | wc -l)
            print_success "Screenshots saved: $screenshot_count"
        fi

        # Check video output
        local result_video=$(find "$PARENT_DIR/results" -name "*.mp4" -type f -newermt "1 minute ago" | head -n 1)
        if [[ -n "$result_video" ]]; then
            local filesize=$(du -h "$result_video" | cut -f1)
            print_success "Result video created: $(basename "$result_video") ($filesize)"
        fi

        print_success "Test recording successful - system is working"
        return 0
    else
        print_error "Test recording failed"
        print_info "Check error messages above for troubleshooting"
        return 1
    fi
}

################################################################################
# Next Steps Guide
################################################################################

show_next_steps() {
    print_header "NEXT STEPS"

    print_step "1. Capture Live Footage"
    echo "   Record from RTSP cameras:"
    echo "   cd $SCRIPTS_ROOT"
    echo "   python3 video_capture/capture_rtsp_streams.py"
    echo ""

    print_step "2. Process Recorded Videos"
    echo "   Run detection on captured footage:"
    echo "   cd $SCRIPTS_ROOT"
    echo "   python3 video_processing/table_and_region_state_detection.py --video ../videos/camera_35.mp4"
    echo ""

    print_step "3. Setup Automated Scheduling (Linux Production)"
    echo "   Configure NTP time sync:"
    echo "   sudo time_sync/setup_ntp.sh"
    echo ""
    echo "   Setup cron jobs for automated recording/processing:"
    echo "   Edit crontab: crontab -e"
    echo ""
    echo "   Example cron schedule:"
    echo "   # Record 11 AM - 9 PM (restaurant hours)"
    echo "   0 11 * * * cd $SCRIPT_DIR && python3 capture_rtsp_streams.py --duration 36000"
    echo ""
    echo "   # Process overnight 11 PM - 6 AM"
    echo "   0 23 * * * cd $SCRIPT_DIR && python3 process_videos_orchestrator.py"
    echo ""

    print_step "4. Monitor System Health"
    echo "   Check GPU usage:"
    echo "   nvidia-smi"
    echo ""
    echo "   Check disk space:"
    echo "   df -h $PARENT_DIR"
    echo ""
    echo "   View recent logs:"
    echo "   sqlite3 $PARENT_DIR/db/detection_data.db \"SELECT * FROM sessions ORDER BY start_time DESC LIMIT 5\""
    echo ""

    print_step "5. Maintenance Tasks"
    echo "   Clean up old videos:"
    echo "   ./cleanup_old_videos.sh"
    echo ""
    echo "   Verify time sync:"
    echo "   ./verify_time_sync.sh"
    echo ""
    echo "   Re-test cameras:"
    echo "   ./run_camera_test.sh"
    echo ""

    print_info "For more details, see: $PARENT_DIR/CLAUDE.md"
}

################################################################################
# Cleanup Handler
################################################################################

cleanup() {
    echo ""
    print_warning "Initialization interrupted"
    exit 130
}

trap cleanup SIGINT SIGTERM

################################################################################
# Main Execution
################################################################################

main() {
    print_header "RTX 3060 PRODUCTION SYSTEM - DEPLOYMENT INITIALIZATION"
    print_info "Restaurant: 野百灵火锅店 (Ye Bai Ling Hotpot)"
    print_info "Location: 1958 Commercial District, Mianyang"
    print_info "Hardware: NVIDIA RTX 3060 Linux Machine"
    echo ""
    print_warning "This script will guide you through initial deployment setup"
    echo ""

    if ! confirm_action "Begin initialization?" "y"; then
        print_info "Initialization cancelled"
        exit 0
    fi

    # Create directories and set permissions
    create_directories
    set_permissions

    # Step 1: Prerequisites
    check_prerequisites

    # Step 2: Camera configuration
    configure_cameras

    # Step 3: ROI configuration
    if $CAMERAS_CONFIGURED; then
        configure_roi
    else
        print_warning "Skipping ROI setup (cameras not configured)"
    fi

    # Step 4: System verification
    verify_system

    # Show deployment report
    show_deployment_report

    # Step 5: Test recording
    if $DEPLOYMENT_READY; then
        test_first_recording
    fi

    # Show next steps
    show_next_steps

    # Final summary
    print_header "INITIALIZATION COMPLETE"

    if $DEPLOYMENT_READY && $CAMERAS_CONFIGURED; then
        print_success "System successfully initialized and ready for production"
        print_info "Start recording: cd $SCRIPTS_ROOT && python3 video_capture/capture_rtsp_streams.py"
        print_info "Process videos: cd $SCRIPTS_ROOT && python3 video_processing/table_and_region_state_detection.py --video <file>"
        exit 0
    else
        print_warning "Initialization partially complete - review checklist above"
        print_info "Re-run this script to complete remaining steps"
        exit 1
    fi
}

# Run main function
main
