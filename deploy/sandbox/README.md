# Sandbox VPS deployment runbook

> **Status.** Phase 1 + Phase 2 are merged on `sandbox-mode`. This directory
> contains the artifacts for [`SANDBOX_PHASES.md`](../../SANDBOX_PHASES.md)
> Phase 3 (VPS provisioning), Phase 4 (staging smoke test), and Phase 5
> (production cutover). Phase 6 automation lives in `.github/workflows/`
> (separate add-on).

## What's in here

| File | Goes to (on VPS) | Phase |
| --- | --- | --- |
| [`docker-compose.sandbox.yml`](docker-compose.sandbox.yml) | layered onto `/opt/metasift/docker-compose.yml` | 3.2 |
| [`Caddyfile`](Caddyfile) | `/etc/caddy/Caddyfile` | 3.4 |
| [`systemd/metasift-om.service`](systemd/metasift-om.service) | `/etc/systemd/system/metasift-om.service` | 3.4 |
| [`systemd/metasift-api.service`](systemd/metasift-api.service) | `/etc/systemd/system/metasift-api.service` | 3.4 |
| [`systemd/metasift-reset.service`](systemd/metasift-reset.service) | `/etc/systemd/system/metasift-reset.service` | 3.4 |
| [`systemd/metasift-reset.timer`](systemd/metasift-reset.timer) | `/etc/systemd/system/metasift-reset.timer` | 3.4 |
| [`.env.sandbox`](.env.sandbox) | reference shape — fill on VPS as `/opt/metasift/.env` | 3.4 |
| [`sudoers.d-metasift`](sudoers.d-metasift) | `/etc/sudoers.d/metasift` | 3.5 |
| [`logrotate-caddy`](logrotate-caddy) | `/etc/logrotate.d/caddy` | 3.5 |

## Prerequisites

- Ubuntu 24.04 LTS VPS (Hostinger KVM2 or equivalent: 2 vCPU / 8 GB RAM / ≥40 GB disk + 8 GB swap recommended). The runbook assumes Debian/Ubuntu — `apt`-based.
- DNS for `metasift.org` you control. The runbook assumes `sandbox.metasift.org` for prod and `sandbox-staging.metasift.org` for Phase 4 staging.
- Free OpenRouter account (no key needed on the VPS — pure BYOK per locked decision §1; the OpenRouter signup is just for verifying the BYO-key flow during smoke tests).
- An SSH keypair you'll add to the VPS for the `metasift` user.

### Cloudflare DNS notes (if you're on Cloudflare, not Hostinger DNS)

The Caddyfile + runbook expect Caddy to provision certs via Let's Encrypt's
HTTP-01 challenge on port 80. Cloudflare's proxy (orange cloud) intercepts
that traffic at its edge — Caddy's challenge never reaches the origin and
issuance silently fails. Two paths:

1. **DNS-only (grey cloud) — recommended for v1.** In Cloudflare's DNS
   panel, set the proxy status of both `sandbox` and `sandbox-staging`
   records to "DNS only" (grey cloud icon). Caddy handles end-to-end TLS;
   Cloudflare is just an authoritative resolver. Simplest path, zero
   plugin churn, no Cloudflare TLS settings to fight with. Trade-off: no
   DDoS shielding from Cloudflare's edge.

2. **Orange cloud + DNS-01 challenge.** Build Caddy with the
   `caddy-dns/cloudflare` plugin (xcaddy add `--with github.com/caddy-dns/cloudflare`),
   create a Cloudflare API token scoped to `Zone:DNS:Edit` on `metasift.org`,
   set it via the Caddyfile's `tls { dns cloudflare {env.CF_API_TOKEN} }`
   directive. Lets you keep the proxy + DDoS shielding. Adds a Cloudflare
   secret to the VPS. Skip for v1, revisit if abuse shows up.

If you go with **(1)**: also turn OFF Cloudflare's "Always Use HTTPS" and
"Automatic HTTPS Rewrites" for `metasift.org` until Caddy's first cert
is issued — those rewrites mid-issuance can break the HTTP-01 callback.

---

## Phase 3.1 — VPS bootstrap (run as root, once)

SSH in and become root if you aren't already:

```bash
sudo -i      # if you SSH'd in as a non-root sudo user (e.g. `hero`)
```

Then, in order — clone FIRST, create the user SECOND, chown LAST. Order
matters: if `adduser` runs before the clone with `--home /opt/metasift`,
it creates an empty `/opt/metasift` directory and the subsequent
`git clone` refuses to write into a non-empty target.

```bash
apt update
# Note: no python3.X-venv — uv (installed below) auto-fetches Python 3.11
# from python-build-standalone, no apt package needed.
#
# IMPORTANT — check for pre-installed Docker before apt-installing.
# Hostinger Ubuntu 24.04 images often ship with `docker-ce` already
# installed from Docker's official repo. Running `apt install docker.io`
# on top of `docker-ce` triggers a package conflict (both provide the
# `/usr/bin/docker` binary). Detect and skip cleanly:
if command -v docker >/dev/null 2>&1 && docker --version | grep -q 'Docker version'; then
  echo "→ Docker already installed: $(docker --version) — skipping docker.io"
  apt install -y docker-compose-plugin make git ufw fail2ban curl jq
else
  apt install -y docker.io docker-compose-plugin make git ufw fail2ban curl jq
fi
systemctl enable --now docker

# Hostinger images may also ship with services bound on common ports.
# Check for pre-existing listeners on 80, 443, 8000, 8585 — anything bound
# there will collide with Caddy / FastAPI / OM.
ss -tlnp | grep -E ':(80|443|8000|8585|8586) ' || echo "→ No conflicts on the ports we need."
# Frequently seen on Hostinger: Cockpit (:9090, :80 redirect), Portainer
# (:8000, :9443), PCP / cockpit-ws. If any of these surface, either:
#   (a) `apt purge` them outright (recommended for cockpit-* / pcp on a
#       single-purpose VPS), OR
#   (b) rebind to loopback so they don't conflict and don't take public
#       ports — for Portainer specifically, edit
#       /etc/systemd/system/portainer.service (or the docker run flags)
#       to publish only `127.0.0.1:9443:9443` and drop the :8000 edge
#       agent binding (single-node Portainer doesn't need it).

# Clone the repo BEFORE creating the metasift user.
git clone --branch sandbox-mode https://github.com/blueberrylinux/metasift.git /opt/metasift

# Create the service user using /opt/metasift as its home.
# adduser does NOT touch ownership of an already-existing dir, so the clone
# is safe; we set ownership explicitly with chown next.
adduser --system --group --shell /bin/bash --home /opt/metasift metasift
chown -R metasift:metasift /opt/metasift

# Add metasift to the docker group. The systemd unit metasift-om.service
# runs `docker compose` as the metasift user, which needs read/write on
# /var/run/docker.sock — that socket is owned by `root:docker`. Without
# this, `systemctl start metasift-om.service` fails with "permission
# denied while trying to connect to the Docker daemon socket".
usermod -aG docker metasift

# Firewall — only SSH + HTTP + HTTPS exposed.
ufw default deny incoming
ufw allow ssh
ufw allow 80
ufw allow 443
ufw --force enable

# SSH hardening — key-only, no passwords. Do this AFTER you've confirmed
# you can log in with your key, otherwise you'll lock yourself out.
#
# IMPORTANT — Hostinger / cloud-init drop-in gotcha. Many Ubuntu cloud
# images (Hostinger included) ship cloud-init with a drop-in at
# `/etc/ssh/sshd_config.d/50-cloud-init.conf` that sets
# `PasswordAuthentication yes`. The drop-in is parsed AFTER the main
# sshd_config and sshd uses first-match-wins per option, so editing
# /etc/ssh/sshd_config does NOTHING — passwords still work. Patch the
# drop-in too, and disable cloud-init's pwauth so it doesn't get
# re-applied on next boot.
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
if [ -f /etc/ssh/sshd_config.d/50-cloud-init.conf ]; then
  sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config.d/50-cloud-init.conf
fi
# Persist across cloud-init re-runs (e.g. after image rebuild):
mkdir -p /etc/cloud/cloud.cfg.d
cat > /etc/cloud/cloud.cfg.d/99-disable-pwauth.cfg <<'EOF'
ssh_pwauth: false
EOF
systemctl restart ssh
# Verify — sshd's effective config (after both files merged) should say no:
sshd -T 2>/dev/null | grep -i passwordauthentication
# → expect "passwordauthentication no"

# fail2ban for SSH only — no web jail (Caddy rate-limit handles that;
# false positives on a public demo are bad UX).
systemctl enable --now fail2ban
```

Install Node (still as root — the `metasift` user has narrow sudo and
can't apt-install). Heads-up: NodeSource sometimes rolls the
`setup_20.x` script forward to a newer LTS (e.g. installs Node 22 or
Node 24 instead of Node 20) without renaming the script. The SPA build
works on any Node ≥20, so accept whatever lands; if you need an exact
pin, swap to `setup_20.x` → `setup_22.x` once 22 is your target LTS, or
use [nvm](https://github.com/nvm-sh/nvm) for hard pinning.

```bash
# Still as root.
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs
node --version   # → v20.x or newer LTS
```

Switch to the `metasift` user for the rest. uv is installed under
`~/.local/bin` (no sudo needed) and auto-fetches Python 3.11 — no system
Python package required:

```bash
sudo -iu metasift

curl -LsSf https://astral.sh/uv/install.sh | sh
# uv install adds itself to PATH via ~/.bashrc; pick it up in this shell:
. "$HOME/.local/bin/env" 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
uv --version

cd /opt/metasift
make install                       # uv venv (fetches Python 3.11) + deps
cd web && npm ci && npm run build  # static React bundle for SERVE_STATIC=1
exit                               # back to root
```

---

## Phase 3.2 — Compose port-binding fix

The dev `docker-compose.yml` exposes OM on `0.0.0.0:8585` for local
convenience. On a public VPS that is a major security hole — OM admin UI
would be reachable from the internet. The override at
[`docker-compose.sandbox.yml`](docker-compose.sandbox.yml) re-binds to
`127.0.0.1:8585` and trims the ES heap.

It's already in place under `/opt/metasift/deploy/sandbox/` from the
`git clone` above. The systemd unit `metasift-om.service` automatically
layers it on top of the dev compose — no further action needed.

If you need to verify by hand — **do this every time the override file
changes**, since Compose merges `ports:` lists additively by default and
a missing `!override` tag silently exposes OM publicly:

```bash
sudo -iu metasift
cd /opt/metasift
docker compose \
  -f docker-compose.yml \
  -f deploy/sandbox/docker-compose.sandbox.yml \
  config | grep -E 'published|target' | head -10
# → for openmetadata-server, should show ONLY:
#     published: "8585", host_ip: 127.0.0.1
#     published: "8586", host_ip: 127.0.0.1
# → if you also see published without host_ip (or with 0.0.0.0), the
#   `!override` tag in the override file got lost — fix before booting.
```

---

## Phase 3.3 — Build Caddy with the rate-limit plugin

Plain `apt install caddy` ships without the
[`caddy-ratelimit`](https://github.com/mholt/caddy-ratelimit) plugin our
[`Caddyfile`](Caddyfile) requires. Build a custom binary with `xcaddy`:

```bash
# As root.
apt install -y golang-go
export GOPATH=/root/go
export PATH=$PATH:$GOPATH/bin
go install github.com/caddyserver/xcaddy/cmd/xcaddy@latest

xcaddy build \
  --with github.com/mholt/caddy-ratelimit
mv caddy /usr/local/bin/caddy
chmod +x /usr/local/bin/caddy

# Create the system user + directories Caddy expects (the apt package
# normally does this).
useradd --system --home /var/lib/caddy --shell /usr/sbin/nologin caddy
mkdir -p /var/lib/caddy /var/log/caddy /etc/caddy
chown -R caddy:caddy /var/lib/caddy /var/log/caddy
caddy --version   # confirm the build succeeded
```

If the xcaddy build is painful (Go version mismatch, network restrictions,
etc.), the fallback is NGINX with `limit_req_zone` —
[SANDBOX_PHASES.md §"Risks"](../../SANDBOX_PHASES.md#risks) item 3
documents the swap. The Caddyfile in this directory is the recommended path.

### Validate the Caddyfile before reloading

The `caddy-ratelimit` plugin's exact directive syntax can drift between
versions. After dropping the Caddyfile in place — and BEFORE running
`systemctl reload caddy` — always validate:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

A failed validation prints the offending line. The two known-good forms
are documented as a comment block in the Caddyfile itself. Reloading
with a broken config takes the public site offline until a fix lands —
don't skip this step.

---

## Phase 3.4 — Place files

All as **root**:

```bash
SRC=/opt/metasift/deploy/sandbox

# Caddy
install -o caddy -g caddy -m 644 $SRC/Caddyfile /etc/caddy/Caddyfile

# Caddy systemd unit (the apt package supplies one; if you used xcaddy,
# create a minimal one):
cat > /etc/systemd/system/caddy.service <<'EOF'
[Unit]
Description=Caddy
After=network-online.target
Wants=network-online.target

[Service]
User=caddy
Group=caddy
ExecStart=/usr/local/bin/caddy run --config /etc/caddy/Caddyfile
ExecReload=/usr/local/bin/caddy reload --config /etc/caddy/Caddyfile
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
AmbientCapabilities=CAP_NET_BIND_SERVICE
ProtectHome=true
ReadWritePaths=/var/lib/caddy /var/log/caddy

[Install]
WantedBy=multi-user.target
EOF

# MetaSift systemd units
install -o root -g root -m 644 $SRC/systemd/metasift-om.service       /etc/systemd/system/
install -o root -g root -m 644 $SRC/systemd/metasift-api.service      /etc/systemd/system/
install -o root -g root -m 644 $SRC/systemd/metasift-reset.service    /etc/systemd/system/
install -o root -g root -m 644 $SRC/systemd/metasift-reset.timer      /etc/systemd/system/

# Sudoers (narrow — only the two restart commands)
install -o root -g root -m 440 $SRC/sudoers.d-metasift /etc/sudoers.d/metasift
visudo -c   # syntax check; fail loud if non-zero

# Logrotate for Caddy access logs
install -o root -g root -m 644 $SRC/logrotate-caddy /etc/logrotate.d/caddy

systemctl daemon-reload
```

### Fill in `/opt/metasift/.env`

The reference template is at [`.env.sandbox`](.env.sandbox). Copy it and
fill in `OPENMETADATA_JWT_TOKEN` + `AI_SDK_TOKEN` once OM is up (next
step generates these). Do NOT pre-fill any `OPENROUTER_API_KEY` — sandbox
is pure BYOK per the locked decisions.

```bash
sudo -iu metasift
cp /opt/metasift/deploy/sandbox/.env.sandbox /opt/metasift/.env
chmod 600 /opt/metasift/.env
# JWT placeholders are filled in §3.6 below after first OM boot.
```

---

## Phase 3.5 — Hardening checklist

The bootstrap (§3.1) handled most of this. Confirm:

```bash
# As root
ufw status                   # → Status: active, only 22/80/443 ALLOW
sshd -T | grep -i password   # → passwordauthentication no
systemctl is-enabled fail2ban   # → enabled
ls -la /opt/metasift/.env    # → -rw------- metasift metasift
ls -la /etc/sudoers.d/metasift  # → -r--r----- root root
test -d /var/log/caddy && echo OK   # → OK
```

Items NOT covered by bootstrap (do these now):

- **Streamlit binding.** The repo's Streamlit app is reachable on `:8501`
  by default, BUT the systemd units don't start it — `metasift-api.service`
  only launches uvicorn. Streamlit is therefore not bound on the public
  iface. If you ever need to inspect it, use an SSH tunnel:
  `ssh -L 8501:127.0.0.1:8501 vps -- uv run streamlit run app/main.py`.
- **OpenRouter dashboard cap.** N/A in v1 — we dropped the fallback OR
  key per the locked decisions, so there's no shared OpenRouter spend
  to cap. Each visitor's BYO key is rate-limited by OpenRouter itself.

---

## Phase 3.6 — First boot

```bash
# Start OM stack first — takes ~2 min for MySQL + ES to come up + the
# migrate one-shot to populate the schema. Watch progress:
sudo systemctl enable --now metasift-om.service
sudo journalctl -u metasift-om.service -f
# When you see "Server started" on port 8585, OM is ready. Ctrl-C the journal.

# Fetch the ingestion-bot JWT — OM creates a fresh one on first volume
# bootstrap. Two ways:
#
# OPTION A (recommended — no SSH tunnel needed). Hit OM's API directly
# from the VPS, log in as the seeded admin user, then read the
# ingestion-bot's auth mechanism (which contains its JWT). One-liner:
#
#   ADMIN_JWT=$(curl -s -X POST http://127.0.0.1:8585/api/v1/users/login \
#     -H "Content-Type: application/json" \
#     -d '{"email":"admin@openmetadata.org","password":"admin"}' | jq -r .accessToken)
#
#   BOT_USER_ID=$(curl -s "http://127.0.0.1:8585/api/v1/bots/name/ingestion-bot" \
#     -H "Authorization: Bearer $ADMIN_JWT" | jq -r .botUser.id)
#
#   BOT_JWT=$(curl -s "http://127.0.0.1:8585/api/v1/users/auth-mechanism/$BOT_USER_ID" \
#     -H "Authorization: Bearer $ADMIN_JWT" | jq -r .config.JWTToken)
#
#   /opt/metasift/.venv/bin/python /opt/metasift/scripts/sandbox_rotate_om_token.py "$BOT_JWT"
#
# This is the path the VPS-side operator validated end-to-end on Hostinger.
# Verified once on a fresh deploy → ingestion-bot JWT roundtripped cleanly,
# scripts/sandbox_rotate_om_token.py wrote .env + restarted the API.
# Future enhancement: fold the curl chain into a `make rotate-jwt` target
# so it's a single command (currently four lines + the rotation script).
#
# OPTION B (fallback — manual via UI). If for any reason the API auth
# flow is hosed (admin password rotated, OM upgrade in flight, etc.):
#
#   ssh -L 8585:127.0.0.1:8585 vps
#   → http://localhost:8585  (admin@openmetadata.org / admin)
#   → Settings → Bots → ingestion-bot → reveal/generate token, copy it
#
#   /opt/metasift/.venv/bin/python /opt/metasift/scripts/sandbox_rotate_om_token.py "<paste-jwt>"
#
# The nightly reset.timer NEVER triggers a re-rotation — it does a soft
# reset that leaves the OM volumes (and JWT) untouched. You only re-run
# the rotation script after a manual `make reset-all`.

# Now boot the API + Caddy
sudo systemctl enable --now metasift-api.service
sudo systemctl enable --now caddy
sudo systemctl enable --now metasift-reset.timer
sudo systemctl list-timers metasift-reset.timer    # confirms next 04:00 UTC fire

# Seed the catalog with demo data
sudo -u metasift bash -c 'cd /opt/metasift && make seed'

# Smoke
curl -s http://127.0.0.1:8000/api/v1/health | jq .
# → expect {"ok": true|false, ..., "sandbox": true, ...}
```

---

## Reset model: soft nightly + occasional manual full

Two reset paths, by design:

### Nightly soft reset — automatic (`metasift-reset.timer`)

Fires daily at 04:00 UTC. Wipes ONLY MetaSift's local SQLite — conversations,
review queue rows, scan history. **Does NOT touch OM's MySQL/ES volumes**,
so the `ingestion-bot` JWT in `/opt/metasift/.env` stays valid forever
across nightly resets. Sub-second; the API restart that follows is ~5s.
No JWT rotation, no manual operator step, no nightly downtime.

Trade-off (intentional): visitor write-backs to OM (accepted descriptions,
PII tag changes from the review queue) accumulate until you fire a manual
full reset. This matches the "shared sandbox" model already documented
in [SANDBOX_DEPLOYMENT_PLAN.md §7](../../SANDBOX_DEPLOYMENT_PLAN.md) —
visitor edits to the seed catalog are visible to the next visitor; only
the chat/review surfaces churn nightly.

### Manual full reset — when drift gets noisy (~weekly)

When the catalog has accumulated enough visitor noise that you want a
clean seeded state, run the full path on the VPS as `metasift`:

```bash
sudo -iu metasift
cd /opt/metasift
make reset-all   # wipes OM volumes + sqlite. ~2 min until OM is back up.
# OM regenerates ingestion-bot with a NEW token. Fetch it:
ssh -L 8585:127.0.0.1:8585 vps   # from your laptop, separate session
# → http://localhost:8585 → admin@openmetadata.org/admin → Bots → ingestion-bot → reveal token
# Back on the VPS:
/opt/metasift/.venv/bin/python scripts/sandbox_rotate_om_token.py "<paste-jwt>"
make seed
```

[`scripts/sandbox_rotate_om_token.py`](../../scripts/sandbox_rotate_om_token.py)
validates the new JWT against OM before writing, atomically rewrites
`/opt/metasift/.env` (preserving every other var), restores `chmod 600`,
and restarts `metasift-api.service` via the sudoers entry. Three-step
process turns into one shell command. Never logs the JWT.

The same script is also used during first-boot Phase 3.6 — see below.

---

## Phase 4 — Staging smoke test

Pre-prod: in **Cloudflare** DNS, add an A record
`sandbox-staging.metasift.org → <VPS IPv4>`, proxy status **DNS only
(grey cloud)**, TTL Auto. The Caddyfile already has a staging block —
Caddy will auto-issue a Let's Encrypt cert for it on first request.

Run the 13-item checklist in
[SANDBOX_PHASES.md §4.2](../../SANDBOX_PHASES.md#42-smoke-checklist) in
an incognito window. Critical items to NOT skip:

- BYO-key modal fires on first chat (402 trap).
- Accept on a review item → 403 sandbox_read_only.
- `curl https://<VPS-IP>:8585` from a different machine → connection
  refused (OM properly internal).
- A second visitor (different cookie) cannot see the first visitor's
  conversation list.
- SSE chat stream works — kick off a tool-heavy turn (e.g. "auto-doc
  the sales schema") and verify it doesn't hang at 60s. The
  `flush_interval -1` + `response_header_timeout 3m` Caddyfile knobs
  matter here.
- Manually fire the nightly soft reset:
  `sudo systemctl start metasift-reset.service` →
  `journalctl -u metasift-reset.service -f` shows `make reset-metasift`
  wiping `metasift.sqlite` then `systemctl restart metasift-api.service`
  bringing the API back up. ~5s end-to-end. The OM stack and JWT are
  untouched (that's the whole point of the soft-reset model).

If everything passes, proceed to Phase 5. If anything fails, fix on
staging — public DNS isn't repointed yet.

---

## Phase 5 — Production DNS cutover

In **Cloudflare** DNS for `metasift.org`: change the existing `sandbox` A
record's value from the Railway IP (current placeholder) to the VPS IPv4.
Keep proxy status set to **DNS only (grey cloud)** — orange cloud breaks
Caddy's HTTP-01 cert renewal, see prerequisites § "Cloudflare DNS notes".
TTL: leave at the default Auto (≈300s) — propagation is minutes, not hours.

```bash
# Verify on the VPS as Caddy issues the prod cert:
sudo journalctl -u caddy -f
# Expect "certificate obtained successfully" within a minute of the first
# visitor hit on https://sandbox.metasift.org.
```

After the prod cert is live, **delete the staging block from the
Caddyfile** to stop issuing extra certs:

```bash
sudo $EDITOR /etc/caddy/Caddyfile   # remove the sandbox-staging block
sudo systemctl reload caddy
```

The Railway service stays alive — that's kill-switch 2 (DNS flip back
to Railway = "demo paused for maintenance" page).

---

## Rollback / kill switches

Per [SANDBOX_DEPLOYMENT_PLAN.md §16](../../SANDBOX_DEPLOYMENT_PLAN.md):

1. `sudo systemctl stop metasift-api.service` — page returns 502 from
   Caddy. OM keeps running. Cheapest stop.
2. DNS flip `sandbox.metasift.org` back to Railway IP. ~minutes via
   TTL=300. The Railway service serves the maintenance page.
3. If a bot wave shows up: enable Cloudflare in front of the VPS in
   "Under Attack" mode (also requires the DNS-only/grey-cloud pattern
   per §3 of the deployment plan).

The 04:00 UTC reset is the daily insurance — if state gets weird mid-day,
manually fire `sudo systemctl start metasift-reset.service` to bring it
back without a full restart cycle.
