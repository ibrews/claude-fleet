# SECURITY ANALYSIS: Shell/Command Injection Vectors

## Files checked for injection vulnerabilities:
1. send-notification.sh - $TARGET, $SUBJECT in git commit
2. send-notification.js - subject in git commit  
3. send-notification-node.js - target, subject in git commit
4. kb-session-end.js - machine name in git commit
5. kb-session-end.sh - MACHINE_NAME in git commit
6. fleet-task.js - opts.tools input validation

## Key findings:
