#!/bin/sh
# OWL focus mode for macOS (CR-085). Run once on the Mac: sudo sh install_owl_focus.sh
# Installs /usr/local/sbin/owl-focus (root-owned) and allows the OWL user to run
# it without a password. "on" pauses Spotlight indexing and the software-update
# schedule for the duration of a measurement.
# 2026-10-06 (owner decision, after the GoS2 focus benchmark): Spotlight indexing
# is PERMANENTLY off on GoS2 (`sudo mdutil -a -i off`, once). Re-enabling it after
# every job ("off") made Spotlight catch up between jobs — mds at up to 555 % CPU,
# idle +0.55 W with bursts to 7 W, spilling into the next measurement — so "off"
# no longer re-enables it. "on" still asserts it off (harmless if already off).
# The software-update schedule likewise stays off (a headless server).
set -e
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
mkdir -p /usr/local/sbin
cat > /usr/local/sbin/owl-focus <<'W'
#!/bin/sh
# owl-focus on|off — pause/restore macOS background work around an OWL measurement
case "$1" in
  on)  mdutil -a -i off >/dev/null 2>&1; softwareupdate --schedule off >/dev/null 2>&1; echo "focus on" ;;
  off) echo "focus off (Spotlight stays off — permanent on this node)" ;;
  *)   echo "usage: owl-focus on|off" >&2; exit 2 ;;
esac
W
chown root:wheel /usr/local/sbin/owl-focus; chmod 755 /usr/local/sbin/owl-focus
tmp=$(mktemp)
printf '%s\n' "# OWL focus mode (CR-085)" "gos ALL=(root) NOPASSWD: /usr/local/sbin/owl-focus on, /usr/local/sbin/owl-focus off" > "$tmp"
visudo -cf "$tmp" >/dev/null && install -m 0440 -o root -g wheel "$tmp" /etc/sudoers.d/owl-focus
rm -f "$tmp"; echo "owl-focus installed"
