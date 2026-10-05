#!/bin/sh
# OWL focus mode for macOS (CR-085). Run once on the Mac: sudo sh install_owl_focus.sh
# Installs /usr/local/sbin/owl-focus (root-owned) and allows the OWL user to run
# it without a password. "on" pauses Spotlight indexing and the software-update
# schedule for the duration of a measurement; "off" restores them.
set -e
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
mkdir -p /usr/local/sbin
cat > /usr/local/sbin/owl-focus <<'W'
#!/bin/sh
# owl-focus on|off — pause/restore macOS background work around an OWL measurement
case "$1" in
  on)  mdutil -a -i off >/dev/null 2>&1; softwareupdate --schedule off >/dev/null 2>&1; echo "focus on" ;;
  off) mdutil -a -i on  >/dev/null 2>&1; echo "focus off" ;;
  *)   echo "usage: owl-focus on|off" >&2; exit 2 ;;
esac
W
chown root:wheel /usr/local/sbin/owl-focus; chmod 755 /usr/local/sbin/owl-focus
tmp=$(mktemp)
printf '%s\n' "# OWL focus mode (CR-085)" "gos ALL=(root) NOPASSWD: /usr/local/sbin/owl-focus on, /usr/local/sbin/owl-focus off" > "$tmp"
visudo -cf "$tmp" >/dev/null && install -m 0440 -o root -g wheel "$tmp" /etc/sudoers.d/owl-focus
rm -f "$tmp"; echo "owl-focus installed"
