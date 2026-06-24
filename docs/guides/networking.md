# Sharing MailCue across projects

Run one MailCue container as a shared development dependency that multiple consumer projects connect to over a Docker network.

## Sharing mailcue across projects

MailCue is designed as a **shared development dependency**. Multiple consumer
projects (fase, and other Olib products) can talk to a single running MailCue
container at the same time without embedding it in their own compose files.
Coupling happens at the Docker-network layer, so mailcue stays standalone.

### One-time host setup

```bash
# Create the shared external network (once per host, never again)
docker network create mailcue-net
```

### Bring up mailcue

```bash
cd /path/to/mailcue
docker compose up -d
```

MailCue attaches to `mailcue-net` with a **static IPv4**, by default
`172.28.0.10`. Override via the `MAILCUE_SANDBOX_IP` env var if that address
collides with another network on your host:

```bash
MAILCUE_SANDBOX_IP=172.28.0.20 docker compose up -d
```

### Consumer-project integration

Inside a consumer project's own `docker-compose.yml` (or its dev-only
`docker-compose.override.yml`) declare the network as external, attach the
services that need MailCue, and map every hostname you want to intercept to
MailCue's IP via `extra_hosts`:

```yaml
services:
  backend:
    # ... your service definition ...
    networks:
      - your-project-net    # your project's own bridge
      - mailcue-net         # shared mailcue bridge
    extra_hosts:
      # Email - resolve mailcue's FQDN to its IP
      - "mail.mailcue.local:172.28.0.10"
      # Outbound HTTP(S) interception - point every upstream hostname you
      # want the sandbox to capture at mailcue's Nginx, which serves
      # CA-signed leaf certs for each:
      - "api.example-provider-a.com:172.28.0.10"
      - "api.example-provider-b.com:172.28.0.10"
      # ... etc.

networks:
  mailcue-net:
    external: true
```

The consumer project must also trust mailcue's Root CA so outbound SDKs
complete their TLS handshake. Copy `/var/lib/mailcue/certs/provider_ca.crt`
out of the running container (it is identical to the email CA at
`/etc/ssl/mailcue/ca.crt`) and install it into the consumer's image with
`update-ca-certificates` at build time:

```bash
docker compose exec mailcue \
    cat /var/lib/mailcue/certs/provider_ca.crt \
    > /path/to/consumer/certs/mailcue-ca.crt
```

### Why an external network (not `build: ../mailcue` in your compose)

Baking `build: ../mailcue` or a `mailcue:` service block into a consumer
project's compose couples mailcue's lifecycle (healthchecks, volumes,
`depends_on`) to that consumer. Any other project that needs the same
sandbox either (a) duplicates the coupling, producing two mailcue
containers that can't share state, or (b) breaks when the consumer stops.
An external network inverts that: mailcue owns its own compose, its own
volumes, and its own healthcheck; every consumer just plugs into the bus.

### Production

Production deployments **do not** use `mailcue-net`. Real upstream DNS
resolves to real upstreams; real TLS is validated against real CAs. See
the [Production deployment](production.md) guide for the
`docker-compose.deploy.yml` workflow.
