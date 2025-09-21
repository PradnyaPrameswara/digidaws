#!/bin/bash

# Cloudflare Tunnel Setup Script for DIGIDAWS
# This script helps set up Cloudflare Tunnel for digidaws.site

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Cloudflare Tunnel Setup for DIGIDAWS ===${NC}"

# Function to print colored output
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   print_error "This script must be run as root (use sudo)"
   exit 1
fi

print_info "Starting Cloudflare Tunnel setup..."

# 1. Create cloudflared user if it doesn't exist
if ! id "cloudflared" &>/dev/null; then
    print_info "Creating cloudflared user..."
    useradd -r -s /bin/false cloudflared
else
    print_info "cloudflared user already exists"
fi

# 2. Create necessary directories
print_info "Creating configuration directories..."
mkdir -p /etc/cloudflared
mkdir -p /var/lib/cloudflared
chown cloudflared:cloudflared /var/lib/cloudflared

# 3. Copy configuration file
print_info "Installing configuration file..."
if [ -f "./cloudflare/config.yml" ]; then
    cp ./cloudflare/config.yml /etc/cloudflared/
    chown cloudflared:cloudflared /etc/cloudflared/config.yml
    chmod 600 /etc/cloudflared/config.yml
else
    print_error "config.yml not found in ./cloudflare/ directory"
    exit 1
fi

# 4. Install systemd service
print_info "Installing systemd service..."
if [ -f "./cloudflare/cloudflared.service" ]; then
    cp ./cloudflare/cloudflared.service /etc/systemd/system/
    systemctl daemon-reload
else
    print_error "cloudflared.service not found in ./cloudflare/ directory"
    exit 1
fi

print_warning "MANUAL STEPS REQUIRED:"
echo ""
echo "1. Replace YOUR_TUNNEL_ID in /etc/cloudflared/config.yml with your actual tunnel ID"
echo "2. Place your origin certificate at /etc/cloudflared/cert.pem"
echo "3. Place your tunnel credentials JSON file at /etc/cloudflared/YOUR_TUNNEL_ID.json"
echo ""
echo "To get your origin certificate:"
echo "  - Go to Cloudflare dashboard > SSL/TLS > Origin Server"
echo "  - Create an origin certificate and download cert.pem"
echo ""
echo "To create and configure a tunnel:"
echo "  cloudflared tunnel login"
echo "  cloudflared tunnel create digidaws-tunnel"
echo "  # Note the tunnel ID from the output"
echo ""
echo "DNS Configuration in Cloudflare:"
echo "  - Add CNAME record: www.digidaws.site -> YOUR_TUNNEL_ID.cfargotunnel.com"
echo "  - Add CNAME record: digidaws.site -> YOUR_TUNNEL_ID.cfargotunnel.com"
echo ""
echo "After completing the manual steps, run:"
echo "  sudo systemctl enable cloudflared"
echo "  sudo systemctl start cloudflared"
echo "  sudo systemctl status cloudflared"

print_info "Setup script completed. Please follow the manual steps above."