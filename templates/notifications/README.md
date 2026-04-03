# Fleet Notifications

Create one subdirectory per machine in your fleet:

```
notifications/
├── alpha/
├── beta/
└── gamma/
```

Notification JSON files are written here by senders and cleaned up by the receiver's sync cron. See [docs/10-notifications.md](../../docs/10-notifications.md) for the full protocol.
