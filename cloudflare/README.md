# Cloudflare Tunnel Configuration for DIGIDAWS

This directory contains the configuration files needed to set up Cloudflare Tunnel for digidaws.site.

## Problem Solved

This configuration fixes the tunnel error 1033 by:
1. Specifying the origin certificate path in the configuration
2. Setting up proper systemd service with environment variables
3. Providing correct DNS configuration guidance

## Files

- `config.yml` - Main Cloudflared configuration file
- `config.template.yml` - Template configuration with clear placeholders
- `cloudflared.service` - Systemd service file for automatic startup
- `setup.sh` - Automated setup script
- `troubleshoot.sh` - Diagnostic script for troubleshooting tunnel issues
- `README.md` - This documentation file

## Prerequisites

1. **Install Cloudflared**:
   ```bash
   # Download and install cloudflared
   wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
   sudo dpkg -i cloudflared-linux-amd64.deb
   ```

2. **Cloudflare Account Setup**:
   - Domain must be added to Cloudflare
   - SSL/TLS encryption mode should be "Full" or "Full (strict)"

## Quick Setup

1. **Run the setup script**:
   ```bash
   sudo ./setup.sh
   ```

2. **Complete manual configuration**:
   
   a. **Login to Cloudflare**:
   ```bash
   cloudflared tunnel login
   ```
   
   b. **Create a tunnel**:
   ```bash
   cloudflared tunnel create digidaws-tunnel
   ```
   Note the tunnel ID from the output.
   
   c. **Get Origin Certificate**:
   - Go to Cloudflare Dashboard → SSL/TLS → Origin Server
   - Click "Create Certificate"
   - Download the certificate and save as `/etc/cloudflared/cert.pem`
   
   d. **Update configuration**:
   - Edit `/etc/cloudflared/config.yml`
   - Replace `YOUR_TUNNEL_ID` with your actual tunnel ID
   
   e. **Set DNS Records in Cloudflare Dashboard**:
   ```
   Type: CNAME, Name: www, Target: YOUR_TUNNEL_ID.cfargotunnel.com
   Type: CNAME, Name: @, Target: YOUR_TUNNEL_ID.cfargotunnel.com
   ```

3. **Start the service**:
   ```bash
   sudo systemctl enable cloudflared
   sudo systemctl start cloudflared
   sudo systemctl status cloudflared
   ```

## Configuration Details

### Origin Certificate Path
The main error was fixed by adding the `origincert` directive in `config.yml`:
```yaml
origincert: /etc/cloudflared/cert.pem
```

### Environment Variables
The systemd service sets the `TUNNEL_ORIGIN_CERT` environment variable as a backup:
```
Environment=TUNNEL_ORIGIN_CERT=/etc/cloudflared/cert.pem
```

### Ingress Rules
- `digidaws.site` redirects to `www.digidaws.site` (301 redirect)
- `www.digidaws.site` serves the Flask application on port 8000
- Catch-all returns 404 for unmatched requests

## Troubleshooting

### Quick Diagnosis
Run the troubleshooting script:
```bash
./troubleshoot.sh
```

### Check tunnel status:
```bash
sudo systemctl status cloudflared
sudo journalctl -u cloudflared -f
```

### Verify configuration:
```bash
cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate
```

### Test tunnel connectivity:
```bash
cloudflared tunnel --config /etc/cloudflared/config.yml ingress rule https://www.digidaws.site
```

### Common Issues

1. **Certificate not found**: Ensure `/etc/cloudflared/cert.pem` exists and is readable by cloudflared user
2. **Permission denied**: Check file ownership and permissions
3. **DNS not resolving**: Verify CNAME records in Cloudflare dashboard
4. **Application not responding**: Ensure Flask app is running on port 8000

## Security Notes

- The cloudflared service runs as a non-root user (`cloudflared`)
- Configuration files have restricted permissions (600)
- The service uses security hardening options in systemd

## Integration with DIGIDAWS

The tunnel configuration assumes:
- Flask application runs on `localhost:8000` (configurable via Gunicorn)
- Application handles both `digidaws.site` and `www.digidaws.site` hosts
- SSL termination happens at Cloudflare edge