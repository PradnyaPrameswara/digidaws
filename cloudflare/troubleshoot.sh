#!/bin/bash

# Cloudflare Tunnel Troubleshooting Script for DIGIDAWS

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== DIGIDAWS Cloudflare Tunnel Troubleshooting ===${NC}"
echo ""

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

print_check() {
    echo -e "${BLUE}[CHECK]${NC} $1"
}

# 1. Check if cloudflared is installed
print_check "Checking if cloudflared is installed..."
if command -v cloudflared &> /dev/null; then
    VERSION=$(cloudflared --version 2>/dev/null | head -n1)
    print_info "cloudflared is installed: $VERSION"
else
    print_error "cloudflared is not installed"
    echo "Install with: wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb && sudo dpkg -i cloudflared-linux-amd64.deb"
fi

echo ""

# 2. Check configuration files
print_check "Checking configuration files..."

if [ -f "/etc/cloudflared/config.yml" ]; then
    print_info "Configuration file exists: /etc/cloudflared/config.yml"
    
    # Check if template values are still present
    if grep -q "YOUR_TUNNEL_ID" /etc/cloudflared/config.yml; then
        print_error "Configuration still contains template values (YOUR_TUNNEL_ID)"
    else
        print_info "Configuration appears to have real tunnel ID"
    fi
else
    print_error "Configuration file missing: /etc/cloudflared/config.yml"
fi

if [ -f "/etc/cloudflared/cert.pem" ]; then
    print_info "Origin certificate exists: /etc/cloudflared/cert.pem"
    # Check certificate permissions
    CERT_PERMS=$(stat -c "%a" /etc/cloudflared/cert.pem 2>/dev/null)
    if [ "$CERT_PERMS" = "600" ] || [ "$CERT_PERMS" = "644" ]; then
        print_info "Certificate permissions are secure: $CERT_PERMS"
    else
        print_warning "Certificate permissions might be too open: $CERT_PERMS"
    fi
else
    print_error "Origin certificate missing: /etc/cloudflared/cert.pem"
    echo "Download from: Cloudflare Dashboard > SSL/TLS > Origin Server"
fi

echo ""

# 3. Check systemd service
print_check "Checking systemd service..."
if [ -f "/etc/systemd/system/cloudflared.service" ]; then
    print_info "Systemd service file exists"
    
    if systemctl is-enabled cloudflared &>/dev/null; then
        print_info "Service is enabled"
    else
        print_warning "Service is not enabled (run: sudo systemctl enable cloudflared)"
    fi
    
    if systemctl is-active cloudflared &>/dev/null; then
        print_info "Service is running"
    else
        print_error "Service is not running"
        print_info "Check status with: sudo systemctl status cloudflared"
        print_info "View logs with: sudo journalctl -u cloudflared -f"
    fi
else
    print_error "Systemd service file missing: /etc/systemd/system/cloudflared.service"
fi

echo ""

# 4. Check DIGIDAWS application
print_check "Checking DIGIDAWS application..."
if pgrep -f "gunicorn.*wsgi:application" > /dev/null; then
    print_info "DIGIDAWS application is running (Gunicorn)"
elif pgrep -f "python.*app.py" > /dev/null; then
    print_info "DIGIDAWS application is running (Development)"
else
    print_error "DIGIDAWS application is not running"
    echo "Start with: cd backend && gunicorn -c gunicorn.conf.py wsgi:application"
fi

# Check if port 8000 is listening
if netstat -tuln 2>/dev/null | grep ":8000 " > /dev/null; then
    print_info "Port 8000 is listening"
else
    print_error "Port 8000 is not listening"
fi

echo ""

# 5. Test configuration if cloudflared is available
if command -v cloudflared &> /dev/null && [ -f "/etc/cloudflared/config.yml" ]; then
    print_check "Testing tunnel configuration..."
    
    # Validate ingress rules
    if cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate 2>/dev/null; then
        print_info "Ingress configuration is valid"
    else
        print_error "Ingress configuration is invalid"
    fi
    
    # Test ingress rules
    print_info "Testing ingress rules:"
    echo "  - digidaws.site: $(cloudflared tunnel --config /etc/cloudflared/config.yml ingress rule https://digidaws.site 2>/dev/null || echo 'error')"
    echo "  - www.digidaws.site: $(cloudflared tunnel --config /etc/cloudflared/config.yml ingress rule https://www.digidaws.site 2>/dev/null || echo 'error')"
fi

echo ""

# 6. DNS checks
print_check "Checking DNS configuration..."
if command -v dig &> /dev/null; then
    print_info "Checking DNS records with dig:"
    
    # Check CNAME records
    WWW_CNAME=$(dig +short www.digidaws.site CNAME)
    ROOT_CNAME=$(dig +short digidaws.site CNAME)
    
    if [[ $WWW_CNAME == *".cfargotunnel.com."* ]]; then
        print_info "www.digidaws.site CNAME: $WWW_CNAME"
    else
        print_error "www.digidaws.site CNAME not found or incorrect: $WWW_CNAME"
    fi
    
    if [[ $ROOT_CNAME == *".cfargotunnel.com."* ]]; then
        print_info "digidaws.site CNAME: $ROOT_CNAME"
    else
        print_error "digidaws.site CNAME not found or incorrect: $ROOT_CNAME"
    fi
else
    print_warning "dig command not available, cannot check DNS"
fi

echo ""
print_info "Troubleshooting complete. Check the errors above and refer to cloudflare/README.md for solutions."