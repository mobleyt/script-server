# Script Server

A collection of small, single-purpose web tools for staff. Each tool lives in its own folder under `apps/`, ships as its own container, and is served behind a shared reverse proxy at its own path.

| App | Path | Stack |
|---|---|---|
| [`apps/transcript-converter`](apps/transcript-converter) | `/transcripts/` | Python / Flask |
| [`apps/rev-converter`](apps/rev-converter) | `/rev/` | Python / Flask |
| [`apps/aviary-uploader`](apps/aviary-uploader) | `/aviary/` (password protected) | Python / Flask |

## Conventions for every app

Every app needs to follow these so the proxy can host any of them, in any language, the same way:

1. **Self-contained folder.** `apps/<name>/` holds its own `Dockerfile`, dependencies and README. Apps share no code or runtime.
2. **Serve at `/` on one port inside the container.** Port 8000 by default. The app never hard-codes the public path it's mounted at.
3. **Prefix-aware URLs.** The proxy strips the public prefix (e.g. `/transcripts`) and sends it in `X-Forwarded-Prefix`. Apps must build links, asset URLs and form actions from that header (Flask: `ProxyFix(x_prefix=1)` + `url_for`; PHP: read `$_SERVER['HTTP_X_FORWARDED_PREFIX']`), or else use only relative URLs.
4. **A health endpoint** (`GET /healthz`, or e.g. `/healthz.php` for PHP) returns 200 when the app is ready, and the Dockerfile `HEALTHCHECK` calls it.
5. **Stateless.** Uploads are processed in memory or in temporary storage and nothing persists, so a container can be restarted or replaced at any time.
6. **Config via environment variables**, with sensible defaults, documented in the app's README.
7. **Run as a non-root user.**

## Layout

```
compose.yaml          one service per app, plus the proxy
.env.example          per-server settings (copy to .env)
proxy/
  Caddyfile           site address, security headers, landing page
  routes/*.caddy      one route file per app, imported automatically
  site/index.html     landing page at /, links to every tool
  site/_shared/       site header and tool menu (nav.js, nav.css), included by every page
apps/<name>/          each app: Dockerfile, code, README
```

```
browser ──► Caddy :80/:443 ─┬─ /              landing page
                            ├─ /transcripts/* ──► transcript-converter:8000
                            ├─ /rev/*         ──► rev-converter:8000
                            └─ /aviary/*      ──► aviary-uploader:8000 ──► Aviary API
                                  (prefix stripped, sent as X-Forwarded-Prefix)
```

Only the proxy publishes ports. The apps run on an `internal` Docker network with no outbound internet access, so they can be reached only through the proxy. App containers also run read-only, as non-root, with all Linux capabilities dropped. If one app crashes, the landing page and the other apps keep working; the broken app returns 502 until it recovers.

**Exceptions for the Aviary Uploader.** It calls the Aviary API, so it also joins an `egress` network that has outbound internet access. Only apps that need outbound access should join it. It also creates records in Aviary, so its route (`proxy/routes/aviary.caddy`) requires a username and password. Set `AVIARY_AUTH_USER` and `AVIARY_AUTH_HASH` in `.env` (see `.env.example`), then run `docker compose up -d proxy` so the proxy picks up the new values. Until they're set, `/aviary/` can't be opened. The other tools stay open.

## Deployment

**Server prerequisites:** Docker Engine with the Compose plugin (v2.20+).

```bash
# 1. Get the code onto the server, then:
cd script-server
cp .env.example .env
#    edit .env — at minimum SITE_ADDRESS (see below)

# 2. Build and start everything
docker compose up -d --build

# 3. Check
docker compose ps           # every app should show (healthy)
docker compose logs -f      # follow logs (Ctrl-C to stop)
```

### Choosing `SITE_ADDRESS`

| Situation | Value | Notes |
|---|---|---|
| Public DNS name, Caddy handles HTTPS | `tools.example.edu` | Caddy gets and renews a Let's Encrypt certificate automatically. Ports 80 and 443 must be reachable from the internet, and DNS must already point at the server. |
| Behind a campus load balancer or proxy that terminates TLS | `:80` | Caddy serves plain HTTP. If that upstream proxy adds its own `X-Forwarded-*` headers, raise `TRUSTED_PROXY_HOPS` in the app services to `2`. |
| Local testing | `:80` | Use `HTTP_PORT=8080` if port 80 is taken. |

Certificates are stored in the `caddy_data` volume. Don't delete it, or Caddy will have to request new certificates and may hit Let's Encrypt rate limits.

### Routine operations

```bash
docker compose up -d --build                        # deploy code changes (rebuilds changed apps only)
docker compose up -d --build transcript-converter   # rebuild and restart one app
docker compose restart proxy                        # reload after editing Caddyfile, routes or landing page
docker compose logs --tail 100 transcript-converter
docker compose down                                 # stop everything (volumes and certificates are kept)
```

Logs rotate automatically (5 × 10 MB per container).

## Adding a new app

Say it's a PHP tool to be served at `/reports/`:

1. **Create `apps/report-tool/`** with a `Dockerfile` that follows the conventions above. For PHP, the official Apache image is the simplest option. This sketch is untested, so treat it as a starting point:
   ```dockerfile
   FROM php:8.3-apache
   RUN sed -i 's/Listen 80/Listen 8000/' /etc/apache2/ports.conf \
    && sed -i 's/:80>/:8000>/' /etc/apache2/sites-available/000-default.conf
   COPY src/ /var/www/html/
   USER www-data
   EXPOSE 8000
   HEALTHCHECK CMD curl -fs http://127.0.0.1:8000/healthz.php || exit 1
   ```
   In PHP, build links from `$_SERVER['HTTP_X_FORWARDED_PREFIX'] ?? ''`, or use only relative URLs. Apache needs writable `/var/run/apache2` and `/var/lock/apache2`, so either add those as `tmpfs` entries or drop `read_only` for that service.

2. **Add a service to `compose.yaml`** under `# ---- apps`:
   ```yaml
   report-tool:
     <<: *app-defaults
     build: ./apps/report-tool
     image: script-server/report-tool:latest
   ```

3. **Add `proxy/routes/reports.caddy`**, copying `transcripts.caddy` and changing the path, service name and prefix:
   ```
   redir /reports /reports/ 308
   handle_path /reports/* {
   	reverse_proxy report-tool:8000 {
   		header_up X-Forwarded-Prefix /reports
   	}
   }
   ```

4. **Add the app to the site header and landing page.** Add an entry to `TOOLS` in `proxy/site/_shared/nav.js`, a card to `proxy/site/index.html`, and a row to the app table at the top of this README. Put the shared header in the app's HTML: in `<head>` add `<link rel="stylesheet" href="/_shared/nav.css">`, and as the first thing in `<body>` add `<script src="/_shared/nav.js"></script>`. These root-relative paths are served by the proxy, not by the app. When the app runs on its own, without the proxy, they 404 and the page just has no header.

5. **Deploy:** `docker compose up -d --build`, then `docker compose restart proxy`.
