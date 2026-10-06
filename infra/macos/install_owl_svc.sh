#!/bin/sh
# OWL as a macOS system LaunchDaemon (CR-085). Run once: sudo sh install_owl_svc.sh
# Why the loopback ssh: macOS Local Network privacy blocks LAN access (the Tapo
# plugs, GoS1) for anything launchd starts as user gos — agents AND this daemon
# (tested 2026-10-06: Python direct → "No route to host"), and toggling the
# Local Network entry didn't help. Processes started by sshd are exempt, so the
# daemon runs `ssh gos@127.0.0.1` with a key that is (authorized_keys) limited to
# from=127.0.0.1 and forced to /Users/gos/owl/owl-serve.sh — it can do nothing
# but start OWL. -tt gives the session a tty so OWL dies with it (no orphan
# holding :8000). Runs as user `gos` (UserName), never root. Installs a narrow wrapper
#   /usr/local/sbin/owl-svc install|restart|stop|status
# and a sudo rule allowing ONLY that wrapper without a password (like GoS1's
# wattlab-restart rule).
set -e
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
mkdir -p /usr/local/sbin
cat > /usr/local/sbin/owl-svc <<'W'
#!/bin/sh
P=/Library/LaunchDaemons/org.greeningofstreaming.owl.plist
L=org.greeningofstreaming.owl
case "$1" in
  install)
    mkdir -p /Users/gos/Library/Logs/owl && chown gos:staff /Users/gos/Library/Logs/owl
    cat > "$P" <<'PL'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>org.greeningofstreaming.owl</string>
  <key>UserName</key><string>gos</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/ssh</string><string>-tt</string>
    <string>-i</string><string>/Users/gos/.ssh/id_owl_local</string>
    <string>-o</string><string>BatchMode=yes</string>
    <string>-o</string><string>ServerAliveInterval=30</string>
    <string>gos@127.0.0.1</string>
  </array>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>HOME</key><string>/Users/gos</string>
    <key>HF_HUB_OFFLINE</key><string>1</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/gos/Library/Logs/owl/owl.log</string>
  <key>StandardErrorPath</key><string>/Users/gos/Library/Logs/owl/owl.log</string>
</dict></plist>
PL
    chown root:wheel "$P"; chmod 644 "$P"
    launchctl bootout system/$L 2>/dev/null || true
    launchctl bootstrap system "$P" && echo "owl daemon installed" ;;
  restart) launchctl kickstart -k system/$L && echo "owl restarted" ;;
  stop)    launchctl bootout system/$L && echo "owl stopped" ;;
  status)  launchctl print system/$L 2>/dev/null | grep -E "state =|pid =" | head -2 ;;
  *) echo "usage: owl-svc install|restart|stop|status" >&2; exit 2 ;;
esac
W
chown root:wheel /usr/local/sbin/owl-svc; chmod 755 /usr/local/sbin/owl-svc
tmp=$(mktemp)
printf '%s\n' "# OWL service control (CR-085)" \
  "gos ALL=(root) NOPASSWD: /usr/local/sbin/owl-svc install, /usr/local/sbin/owl-svc restart, /usr/local/sbin/owl-svc stop, /usr/local/sbin/owl-svc status" > "$tmp"
visudo -cf "$tmp" >/dev/null && install -m 0440 -o root -g wheel "$tmp" /etc/sudoers.d/owl-svc
rm -f "$tmp"; echo "owl-svc installed (not started — Claude starts it)"
