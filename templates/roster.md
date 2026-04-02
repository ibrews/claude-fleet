# Fleet Roster

| Machine | Hardware | OS | Role | Tailscale Hostname |
|---------|----------|----|------|--------------------|
| **alpha** | MacBook Pro M-series | macOS | Coordinator | alpha |
| **beta** | Desktop, RTX 4090 | Windows | Heavy Compute | beta |
| **gamma** | Linux server | Linux | General Purpose | gamma |

## Roles

- **Coordinator**: Always-on machine that routes tasks. Runs the fleet trigger script.
- **Heavy Compute**: GPU-heavy workloads — training, rendering, large builds.
- **General Purpose**: Standard development tasks, testing, CI.
- **Light Duty**: Monitoring, simple classification, batch processing.

## Network

All machines connected via [Tailscale](https://tailscale.com/) mesh VPN.
SSH configured for passwordless access between all machines.
