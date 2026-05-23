# Deploy Templates

These templates are safe starting points for a single-host production-style
deployment:

- `nginx/hackme_web.conf.example`: public TLS reverse proxy.
- `systemd/hackme-web.service.example`: bounded Gunicorn web service.
- `systemd/hackme-web.env.example`: environment file consumed by systemd.
- `systemd/hackme-web.tmpfiles.example`: runtime directory creation policy.

Copy them to the host-specific locations only after replacing placeholders such
as domain name, Unix user, project path, certificate path, and secrets.

The web service intentionally runs only the HTTP request lifecycle. Long-running
work such as trading background jobs, HLS generation, BT/direct-link transfers,
and local AI generation should be managed by separate worker services as those
entrypoints are enabled for production.

## Apply Order

1. Prepare the checkout and venv under `/opt/hackme_web`.
2. Install runtime dependencies:

   ```bash
   /opt/hackme_web/.venv/bin/python3 -m pip install -r /opt/hackme_web/requirements-minimal.txt
   ```

3. Install the env file and replace every secret:

   ```bash
   sudo install -m 0640 -o root -g hackme deploy/systemd/hackme-web.env.example /etc/hackme_web/hackme-web.env
   ```

   At minimum, set `HTML_LEARNING_TRUSTED_HOSTS` to the public domain list,
   for example `hackme.example.com,www.hackme.example.com`. Keep
   `HTML_LEARNING_MAX_FORM_MEMORY_KB` and `HTML_LEARNING_MAX_FORM_PARTS`
   configured unless you have a measured production reason to tune them.
   Your reverse proxy must forward the original host, for example
   `proxy_set_header Host $host;`, so Flask can reject untrusted Host headers.

4. Install tmpfiles and create runtime directories:

   ```bash
   sudo install -m 0644 -o root -g root deploy/systemd/hackme-web.tmpfiles.example /etc/tmpfiles.d/hackme-web.conf
   sudo systemd-tmpfiles --create /etc/tmpfiles.d/hackme-web.conf
   ```

5. Install and start the web service:

   ```bash
   sudo install -m 0644 -o root -g root deploy/systemd/hackme-web.service.example /etc/systemd/system/hackme-web.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now hackme-web.service
   ```

6. Install the Nginx site, replace domain/cert paths, then reload:

   ```bash
   sudo cp deploy/nginx/hackme_web.conf.example /etc/nginx/sites-available/hackme_web
   sudo ln -s /etc/nginx/sites-available/hackme_web /etc/nginx/sites-enabled/hackme_web
   sudo nginx -t
   sudo systemctl reload nginx
   ```

7. Verify from the public endpoint:

   ```bash
   curl -ksS https://<host>/api/version
   curl -ksS https://<host>/readyz
   ```

## Do Not

- Do not expose Gunicorn directly to the public internet.
- Do not set `TRUSTED_PROXY_IPS` to a broad public range.
- Do not leave `HTML_LEARNING_TRUSTED_HOSTS` unset for a public hostname.
- Do not pass maintenance bypass tokens in query strings. Use
  `X-Maintenance-Bypass-Token`.
- Do not store production secrets in the git checkout.
- Do not raise Gunicorn worker/thread counts to compensate for HLS, BT, direct
  link, trading background jobs, or local AI generation. Move those into worker
  services instead.
