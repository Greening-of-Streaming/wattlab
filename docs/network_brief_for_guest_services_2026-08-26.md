# Brief for a guest service on the GoS lab network (arr stack + Caddy)

*For the agent setting up the arr stack. Written 2026-08-26. The network is a measurement lab
(Greening of Streaming — OWL/WattLab): it measures streaming energy in watts, so stray traffic,
device wake-ups and port/DHCP changes are not just untidy, they corrupt results and take a public
site offline. Everything below is "hands off unless Ben does it".*

## 1. Where you may live
- **Your own host** (VM/NAS/mini-PC), connected to a **free Bbox LAN port or Wi-Fi** — NOT the bench
  switches (Netgear GS305E-1 / GS305E-2 and anything plugged into them: that is the test rig).
- Take a **plain DHCP lease**. Do not set a static IP by hand — ~20 addresses are router-reserved
  for lab gear (list in §4). If you need a fixed address, ask Ben to add a reservation.
- Run your own Docker on your own host. **Nothing gets installed on GoS1 (`192.168.1.62`).** No
  SSH to it, no containers on it, no Caddy on it.

## 2. The hard constraint: public 80/443 are taken
- The router (Bouygues Bbox `192.168.1.254`, fixed public IP) forwards **80 and 443 → GoS1**
  (nginx + certbot serving `https://wattlab.greeningofstreaming.org`) and **2222 → GoS1:22**.
  These three forwards must not be changed, moved or shared.
- So **Caddy cannot listen on the public 80/443 of this network.** Pick one:
  1. **Recommended — tunnel out:** Cloudflare Tunnel (or Tailscale Funnel) from *your* host. Zero
     router changes, TLS handled upstream, Caddy stays LAN-side on any port.
  2. Ask Ben to add a `server {}` block on GoS1's nginx that proxies your hostname → your host.
     Ben-only (certbot lives on GoS1). Then your box needs no public exposure at all.
  3. A manual high-port forward (e.g. 8443 → your host) added by Ben. Least nice, still acceptable.
- **No UPnP / NAT-PMP.** Turn off "use UPnP to map port" in qBittorrent/Transmission/etc. The
  Bbox port map is curated; apps must not add entries.
- Don't touch DNS: `wattlab.greeningofstreaming.org`, `gos1.duckdns.org` and the DuckDNS cron on
  GoS1 are all live (DuckDNS is deliberate portability insurance — not dead weight).

## 3. Router and switches — do not log in, do not change
- Bbox admin: DHCP reservations, port forwards, "IP fixe" opt-in, IGMP/multicast, DNS. Ben only.
- GS305E switches: IGMP snooping + "Block Unknown Multicast" are set on purpose (IPTV multicast
  flooded GoS1 and flapped its NIC). Don't plug into them, don't change them.
- Don't run your own DHCP server, DNS resolver advertised via DHCP (Pi-hole/AdGuard as network
  DNS), mDNS reflector or VPN that pushes routes to the LAN. Local-only resolvers on your host are fine.

## 4. Lab devices — never address, discover, wake or power them
Reserved `192.168.1.x` (all router-reserved; treat as instruments):

| Address | What |
|---|---|
| `.62` | **GoS1** server (public site, SSH, measurement service :8000, origin :8123, Postgres :5432, :7001, :8080, Samba) |
| `.254` | Bbox router |
| `.10` / `.173`, `.126`, `.200`, `.152`, `.25` / `.109`, `.102`, `.108` | STBs, Apple TV, LG C2 TV, Raspberry Pis under test |
| `.1`, `.31`, `.35`, `.36`, `.71`, `.146`, `.155`, `.159`, `.91`, `.184`, `.17` | Tapo P110 / Shelly power meters |
| `.95`, `.132`, `.199` | Ben's desk plugs |

- **Power meters (Tapo/Shelly):** never poll, pair, adopt into Home Assistant, or switch them. The
  local API allows one session — a second client breaks the lab's readings. **`.35` powers the
  router itself**: switching it off takes the whole LAN down with no remote recovery.
- **Media discovery is the sneaky one.** Plex/Jellyfin/Emby DLNA, Chromecast, AirPlay and
  Wake-on-LAN discovery *wake* the TV, Apple TV and Google TV boxes and put them in a non-idle
  state mid-measurement. **Disable DLNA/SSDP server, Chromecast/AirPlay discovery and any WoL**
  in your media server, or bind it to your host only. Never cast/adb/ssh to the devices above.

## 5. Bandwidth etiquette
OWL runs overnight measurement campaigns (typically 22:00–08:00, sometimes daytime) that include
network-path arms on Wi-Fi and Ethernet. Bulk downloads/uploads during a campaign contaminate
those rows and can slow the public site.
- Rate-limit torrent/usenet clients (suggest ≤ 20 Mbps down / ≤ 5 Mbps up) and cap seeding.
- Prefer scheduling bulk transfers to a window agreed with Ben; assume any hour may be a campaign.
- Don't stream 4K IPTV/multicast to anything on the bench switches.

## 6. Quick checklist before going live
- [ ] Own host, on a Bbox port or Wi-Fi, DHCP lease, no manual IP
- [ ] Public exposure via tunnel (or Ben-added nginx vhost / high-port forward) — not 80/443
- [ ] UPnP off in every app; no router login
- [ ] DLNA / Chromecast / AirPlay / WoL discovery off in the media server
- [ ] Never touch `.62`, the meters, the STBs; nothing installed on GoS1
- [ ] Download/upload rate limits set

Contact for anything on the router, GoS1 or DNS: Ben.
