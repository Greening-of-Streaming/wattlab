### Network-path campaign — batch `20260818ae7ba7b0` — 30 jobs, 54 valid rows, 0 lost

ΔW above device idle (W), 600 s windows, BBB H.264 (hardware decode on the STBs, software on the Pi 400); ± = per-run 95 % CI half-width.

**Pi 400 (software decode; ffmpeg -re → -f null; eth0 vs wlan0 vs local /dev/shm)**

| bitrate | local file (no network) | Ethernet HTTP burst | Ethernet HTTP paced | Wi-Fi HTTP burst | Wi-Fi HTTP paced |
|---|---|---|---|---|---|
| 1.5 Mb/s | **+1.19** ±0.16 🟢 | **+1.39** ±0.14 🟢 | **+1.28** ±0.12 🟢 | **+1.38** ±0.23 🟢 | **+1.13** ±0.16 🟢 |
| 8 Mb/s | **+1.46** ±0.11 🟢 | **+1.37** ±0.14 🟢 | **+1.36** ±0.20 🟢 | **+1.67** ±0.18 🟢 | **+1.88** ±0.12 🟢 |
| 20 Mb/s | — | **+1.28** ±0.17 🟢 | **+1.47** ±0.14 🟢 | **+1.98** ±0.10 🟢 | **+2.04** ±0.10 🟢 |

Ethernet 8 Mb/s burst with the Wi-Fi radio OFF (control): **+1.39** ±0.23 🟢


**Google TV (Ethernet, hardware decode)**

| bitrate | HTTP burst | HTTP paced (1.25× rate) |
|---|---|---|
| 1.5 Mb/s | **+0.41** ±0.05 🟢🟢🟢 | **+0.44** ±0.07 🟢🟢🟢 |
| 8 Mb/s | **+0.52** ±0.06 🟢🟢🟢 | **+0.55** ±0.07 🟢🟢🟢 |
| 20 Mb/s | **+0.58** ±0.06 🟢🟢🟢 | **+0.58** ±0.06 🟢🟢🟢 |

Local file 8 Mb/s (adb push, no network): **+0.50** ±0.09 🟢🟢🟢


**Bbox 4K (Ethernet, hardware decode; idle drifts ±0.3 W)**

| bitrate | HTTP burst | HTTP paced (1.25× rate) |
|---|---|---|
| 1.5 Mb/s | **+0.08** ±0.19 🔴🔴🟢 | **+0.15** ±0.19 🟡🟡🟢 |
| 8 Mb/s | **+0.16** ±0.19 🟡🟢🟢 | **+0.18** ±0.19 🟢🔴🟢 |
| 20 Mb/s | **+0.22** ±0.19 🟢🟢🟢 | **+0.28** ±0.20 🟢🟢🟢 |

**Fire TV Stick (Wi-Fi only)**

| bitrate | HTTP burst | HTTP paced (1.25× rate) |
|---|---|---|
| 1.5 Mb/s | — | — |
| 8 Mb/s | — | — |
| 20 Mb/s | — | — |

Local file 8 Mb/s (adb push, no network): —


Interfaces recorded mid-window on the Pi rows: net_b1500_burst: lo 127.0.0.1/8 eth0 192.168.1.108/24 wlan0 192.168.1.110/24; net_b1500_paced: lo 127.0.0.1/8 eth0 192.168.1.108/24 wlan0 192.168.1.110/24; net_b20000_burst: lo 127.0.0.1/8 eth0 192.168.1.108/24 wlan0 192.168.1.110/24; net_b20000_paced: lo 127.0.0.1/8 eth0 192.168.1.108/24 wlan0 192.168.1.110/24; net_b8000_burst: lo 127.0.0.1/8 eth0 192.168.1.108/24 wlan0 192.168.1.110/24; net_b8000_paced: lo 127.0.0.1/8 eth0 192.168.1.108/24 wlan0 192.168.1.110/24; net_pi_eth_b8000_wifioff: lo 127.0.0.1/8 eth0 192.168.1.108/24; net_pi_local_b1500: lo 127.0.0.1/8 eth0 192.168.1.108/24 wlan0 192.168.1.110/24; net_pi_local_b8000: lo 127.0.0.1/8 eth0 192.168.1.108/24 wlan0 192.168.1.110/24; net_pi_wifi_b1500_burst: lo 127.0.0.1/8 wlan0 192.168.1.110/24; net_pi_wifi_b1500_paced: lo 127.0.0.1/8 wlan0 192.168.1.110/24; net_pi_wifi_b20000_burst: lo 127.0.0.1/8 wlan0 192.168.1.110/24; net_pi_wifi_b20000_paced: lo 127.0.0.1/8 wlan0 192.168.1.110/24; net_pi_wifi_b8000_burst: lo 127.0.0.1/8 wlan0 192.168.1.110/24; net_pi_wifi_b8000_paced: lo 127.0.0.1/8 wlan0 192.168.1.110/24

Lost/excluded rows:

