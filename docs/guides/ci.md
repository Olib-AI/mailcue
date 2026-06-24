# Using in CI/CD

MailCue runs as a service in automated testing pipelines.

## GitHub Actions service

```yaml
# GitHub Actions example
services:
  mailcue:
    image: ghcr.io/olib-ai/mailcue
    ports:
      - 8088:80
      - 25:25
      - 143:143

steps:
  - name: Wait for MailCue
    run: |
      until curl -sf http://localhost:8088/api/v1/health; do sleep 1; done

  - name: Run email tests
    run: npm test
    env:
      SMTP_HOST: localhost
      SMTP_PORT: 25
      MAILCUE_API: http://localhost:8088/api/v1
```

## API keys for non-interactive auth

Use API keys for non-interactive authentication:

```bash
# Create an API key
TOKEN=$(curl -s -X POST http://localhost:8088/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"mailcue"}' | jq -r .access_token)

API_KEY=$(curl -s -X POST http://localhost:8088/api/v1/auth/api-keys \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"ci-pipeline"}' | jq -r .key)

# Use the API key in subsequent requests
curl -H "X-API-Key: $API_KEY" http://localhost:8088/api/v1/emails?mailbox=admin@mailcue.local
```

## CI Platform Examples

Ready-to-use configuration files for popular CI/CD platforms:

| Platform | Example file |
|---|---|
| **GitHub Actions** | [`examples/ci/github-actions.yml`](../../examples/ci/github-actions.yml) |
| **GitLab CI** | [`examples/ci/gitlab-ci.yml`](../../examples/ci/gitlab-ci.yml) |
| **CircleCI** | [`examples/ci/circleci.yml`](../../examples/ci/circleci.yml) |
| **Jenkins** | [`examples/ci/Jenkinsfile`](../../examples/ci/Jenkinsfile) |
| **Bitbucket Pipelines** | [`examples/ci/bitbucket-pipelines.yml`](../../examples/ci/bitbucket-pipelines.yml) |

Each example includes the full pattern: health check wait, authentication, API key creation, email injection, and verification.

See the main [README](../../README.md) for the rest of the documentation.
