# Tailscale Setup

[Tailscale](https://tailscale.com/) creates a WireGuard-encrypted mesh VPN between your machines. Every machine can reach every other machine by hostname — no port forwarding needed.

## Install

### macOS
```bash
brew install tailscale
# Or download from https://tailscale.com/download/mac
```

### Windows
Download from https://tailscale.com/download/windows

### Linux
```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

## Join Your Tailnet

On each machine:
```bash
sudo tailscale up --ssh
```

This enables Tailscale SSH — you can SSH between machines without managing keys.

## Verify

```bash
# See all machines on your tailnet
tailscale status

# Test SSH (use the Tailscale hostname)
ssh alpha
ssh beta
```

## SSH Config (Optional)

If you prefer explicit SSH config, add entries to `~/.ssh/config`:

```
Host alpha
    HostName 100.x.y.z
    User yourusername
    ConnectTimeout 10

Host beta
    HostName 100.x.y.z
    User yourusername
    ConnectTimeout 10
```

## Tips

- **Tailscale's free tier** supports up to 100 devices — more than enough.
- **MagicDNS** lets you use hostnames instead of IPs. Enable it in the Tailscale admin console.
- **Key expiry**: Set keys to not expire for always-on machines (admin console → Machines → Disable key expiry).
- **ACLs**: The default policy allows all machines to reach each other. Only tighten if you need to.
