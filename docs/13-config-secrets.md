## <a name="ch13"></a>13. Configuration & Secrets — ConfigMaps, Secrets & External Secrets

The same **image** must run unchanged in dev, staging, and production — only its **configuration** differs. Baking config or passwords into the image is a security and operability disaster. Kubernetes separates config from code with **ConfigMaps** and **Secrets**, and for real production, an **External Secrets** operator keeps credentials out of Git entirely.

### 13.1 The twelve-factor rule: config lives outside the image

![Config injection](assets/diagrams/13-config-injection.png)

Both ConfigMaps and Secrets inject into a pod the same two ways:

- as **environment variables**, or
- as **mounted files** in a volume.

```yaml
# repo/manifests/40-config/configmaps.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: orders-config
  namespace: tickethub
data:
  LOG_LEVEL: "info"
  PAYMENTS_URL: "http://payments.tickethub.svc.cluster.local"
  KAFKA_BROKERS: "kafka-0.kafka.data:9092,kafka-1.kafka.data:9092"
```

!!! mental "Mental model — one appliance, different wall sockets"
    The image is a **power tool**. The ConfigMap/Secret is the **plug adapter** for
    whichever country (environment) you're in. You don't manufacture a new drill for
    every country — you change the adapter. One image, many environments.

### 13.2 Secrets — same shape, more care

A **Secret** looks like a ConfigMap but is meant for sensitive values (DB passwords, API keys). Values are base64-encoded (**not** encryption on its own) and can be **encrypted at rest** in etcd (Chapter 24).

```yaml
# See: repo/manifests/ for the full manifest
# Illustrative only — NOT committed to Git. Real values are synced by the
# External Secrets Operator (see external-secrets.yaml below).
apiVersion: v1
kind: Secret
metadata:
  name: orders-db
  namespace: tickethub
type: Opaque
stringData:                        # stringData: plaintext in, base64 stored
  DB_PASSWORD: "REPLACED_BY_EXTERNAL_SECRETS"
```

Consuming both in the Deployment:

```yaml
# in the container spec
envFrom:
  - configMapRef: { name: orders-config }   # all keys as env vars
env:
  - name: DB_PASSWORD
    valueFrom:
      secretKeyRef: { name: orders-db, key: DB_PASSWORD }
volumeMounts:
  - name: appcfg
    mountPath: /etc/orders           # config as files
    readOnly: true
volumes:
  - name: appcfg
    configMap: { name: orders-config }
```

!!! warning "base64 is encoding, not encryption"
    `kubectl get secret -o yaml` shows base64 that anyone can decode in one command.
    Secrets protect data via **RBAC** (who can read them, Chapter 19) and **encryption at
    rest** (Chapter 24) — *not* by the base64 itself. Never commit real Secret values to Git.

### 13.3 Env vars vs. mounted files — which to use

| | Environment variables | Mounted files |
|--|----------------------|---------------|
| Ease | Simplest | Slightly more setup |
| **Live updates** | No — needs pod restart | **Yes** — volume updates propagate |
| Leak risk | Visible in `/proc`, crash dumps, `env` | Lower; file perms apply |
| Best for | Small flags, URLs | Large configs, certs, rotating secrets |

For rotating credentials and TLS certs, prefer **mounted files** so rotation doesn't require a restart.

### 13.4 External Secrets — keep credentials out of Git

Storing Secret YAML in Git (even encrypted) is fragile. The **External Secrets Operator (ESO)** keeps the source of truth in a real vault (HashiCorp Vault, AWS Secrets Manager) and **syncs** it into native Kubernetes Secrets. Git holds only a *reference* — the `ExternalSecret` — never the value.

![External secrets](assets/diagrams/13-external-secrets.png)

```yaml
# repo/manifests/40-config/external-secrets.yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: orders-db
  namespace: tickethub
spec:
  refreshInterval: 1h              # re-sync + rotate
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: orders-db                # creates/updates this k8s Secret
  data:
    - secretKey: DB_PASSWORD
      remoteRef:
        key: tickethub/orders
        property: db_password
```

!!! key "GitOps + secrets: reference, never the value"
    In a GitOps world (Chapter 28) the whole cluster is defined in Git — but secrets must
    **not** be. ESO squares the circle: Git stores the *ExternalSecret pointer*, the vault
    stores the *value*, ESO reconciles them into a real Secret. Rotations in the vault
    propagate automatically on the next refresh.

!!! tip "Alternative: Sealed Secrets"
    If you have no external vault, **Sealed Secrets** lets you commit an *encrypted*
    SealedSecret to Git that only the in-cluster controller can decrypt. Good for smaller
    setups; ESO scales better when a real secrets manager already exists.


### 13.5 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - **Mounted ConfigMap volumes update automatically** (eventually consistent, with a kubelet sync delay of `syncPeriod`, default 60s) — but **environment variables from ConfigMaps do NOT update** without a pod restart. This asymmetry catches teams off-guard: changing a feature flag in a ConfigMap takes up to 60s to propagate to volume-mounted configs but requires a rollout for env-var configs.
    - **Kubernetes Secrets are base64-encoded, not encrypted**, by default in etcd. The base64 encoding is not a security measure — anyone with etcd access sees plaintext values. Encryption at rest (`EncryptionConfiguration` with AES-GCM or Vault KMS provider) is a separate cluster-level config (Chapter 24).
    - **ExternalSecret reconciliation interval**: the `ExternalSecret` CR has a `refreshInterval` (default 1 hour). If Vault revokes and reissues a secret (e.g., after a rotation event), the new value won't reach the Kubernetes Secret for up to 1 hour unless you `kubectl annotate externalsecret X force-sync=$(date +%s)` to trigger immediate reconciliation.

!!! warning "Gotchas — traps that catch experienced engineers"
    - **`envFrom: configMapRef` loads ALL keys as env vars**: if a ConfigMap has a key named `JAVA_TOOL_OPTIONS` it will override the JVM settings for every container that mounts it — silently. Prefer `env: valueFrom: configMapKeyRef` for explicit key selection in production.
    - **Secret data keys with unsupported characters**: Kubernetes Secret keys must match `[-._a-zA-Z0-9]`. A key named `db.password` (with a dot) is valid, but many application frameworks that read env vars convert dots to underscores or vice versa. Use consistent naming conventions.
    - **ExternalSecret fails silently if the Vault path doesn't exist**: the ExternalSecret controller sets a `Ready=False` condition on the CR, but the application pod starts anyway with the PREVIOUS secret value if the Kubernetes Secret already exists from a prior sync. Monitoring ExternalSecret conditions is non-optional.

!!! question "Architect Considerations"
    1. **ConfigMap vs environment variable vs Vault secret decision tree**: use ConfigMaps for non-sensitive tunable configuration (log levels, feature flags, URLs). Use Secrets (backed by Vault via ExternalSecret) for credentials, tokens, and API keys. Never use ConfigMaps for secrets, even temporarily.
    2. **Secret rotation zero-downtime strategy**: when a database password is rotated in Vault, ExternalSecret updates the Kubernetes Secret, but running pods don't see the update until they restart. Design connection pool reconnect logic (Postgres `target_session_attrs`, JDBC retry) to handle mid-session password changes, or coordinate pod rolling restarts with the rotation event.
    3. **Vault namespace isolation**: does each team's ExternalSecret pull from a separate Vault namespace/path with its own policy? Sharing a single Vault policy that allows reading ALL secrets gives each service blast radius equal to the entire secret store — violates least privilege.
    4. **Configuration drift detection**: with ConfigMaps managed by GitOps (Argo CD), a manual `kubectl edit configmap` creates drift that Argo CD will revert. Ensure your runbooks instruct operators to make configuration changes through git, not kubectl, to avoid surprise rollbacks.
    5. **Sealed Secrets vs External Secrets**: Sealed Secrets encrypt secret values in git (useful for small teams without a Vault instance). External Secrets pull from an external store at runtime (better for enterprise governance). Choose based on your secret management maturity — Vault + External Secrets is the correct long-term architecture.

!!! success "Chapter 13 checklist"
    - **One image per service** across all environments; config injected, never baked in.
    - Non-secret settings in **ConfigMaps**; sensitive values in **Secrets**.
    - Secrets protected by **RBAC** + **encryption at rest**, never committed as plaintext.
    - Rotating creds/certs mounted as **files** for restart-free updates.
    - Real credentials sourced via **External Secrets** (or Sealed Secrets); Git holds references only.

---
