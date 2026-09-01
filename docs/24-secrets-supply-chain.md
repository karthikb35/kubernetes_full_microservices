## <a name="ch24"></a>24. Secrets at Rest, Image Signing & Supply-Chain Security

The final preventive layer protects two things attackers love: the **secrets stored in etcd** and the **images you run**. A secret is only as safe as the disk under etcd; an image is only as trustworthy as its provenance. This chapter encrypts the former and cryptographically verifies the latter.

### 24.1 Encrypting Secrets at rest

By default, Kubernetes Secrets are stored in etcd as **base64 — not encrypted** (Chapter 13). Anyone with etcd disk access or a backup reads them plainly. An **EncryptionConfiguration** encrypts them before they hit disk.

![Encryption at rest](assets/diagrams/24-encryption-at-rest.png)

```yaml
# See: repo/manifests/ for the full manifest
# /etc/kubernetes/enc/encryption-config.yaml (referenced by kube-apiserver flag)
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources: ["secrets"]
    providers:
      - kms:                          # best: key lives in an external KMS/Vault
          name: vault-kms
          endpoint: unix:///var/run/kmsplugin/socket.sock
      - aescbc:                       # fallback local key
          keys:
            - name: key1
              secret: <base64-32-byte-key>
      - identity: {}                  # read old plaintext during migration
```

```bash
# apiserver flag:  --encryption-provider-config=/etc/kubernetes/enc/encryption-config.yaml
# re-encrypt existing secrets after enabling:
kubectl get secrets -A -o json | kubectl replace -f -
```

!!! key "KMS provider beats a local key"
    A local `aescbc` key sits on the control-plane node — steal the node, steal the key.
    A **KMS provider** (Vault, cloud KMS) keeps the **key-encryption-key off the cluster**;
    the apiserver calls out to decrypt, so an etcd backup alone is useless to an attacker.
    For a payments platform, KMS is the standard.

!!! mental "Mental model — a safe vs. a locked safe with the key elsewhere"
    Base64 secrets in etcd are documents in an **unlocked drawer**. `aescbc` locks the
    drawer but tapes the **key to the bottom**. **KMS** locks the drawer and keeps the key
    in a **different building** (the KMS) that logs every access. Only the last one
    protects you when someone walks off with the drawer (an etcd backup).

### 24.2 Image signing — trust what you run

Chapter 10 built and scanned images. But how does the cluster know an image is **really yours** and unmodified? **Sign** it with cosign, and **verify** the signature at admission — refuse anything unsigned.

![Image signing](assets/diagrams/24-image-signing.png)

```yaml
# repo/manifests/60-security/kyverno-policies.yaml (verify-images section)
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata: { name: verify-image-signatures }
spec:
  validationFailureAction: Enforce
  rules:
    - name: verify-tickethub-images
      match:
        any: [{ resources: { kinds: [Pod] } }]
      verifyImages:
        - imageReferences: ["registry.internal/tickethub/*"]
          attestors:
            - entries:
                - keys:
                    publicKeys: |-
                      -----BEGIN PUBLIC KEY-----
                      MFkwEwYHKoZ...          # cosign public key
                      -----END PUBLIC KEY-----
```

Now an unsigned or tampered image is **denied at admission** — the supply chain is closed loop: build → scan → sign (Ch 10) → **verify** (here).

### 24.3 The full supply-chain picture

| Stage | Control | Chapter |
|-------|---------|---------|
| Build | Multi-stage, distroless, non-root | 10 |
| Scan | Trivy blocks HIGH/CRITICAL CVEs | 10 |
| **Sign** | cosign signs the digest | 10 |
| Provenance | SBOM + SLSA attestation | 24 |
| **Verify** | Kyverno denies unsigned images | 24 |
| Run | PSA + SecurityContext | 20 |
| Watch | Falco runtime detection | 23 |

!!! warning "Pin by digest, not tag, to make signatures meaningful"
    A signature covers an **image digest** (`@sha256:...`). If you deploy by mutable tag,
    the tag can be repointed to a different (unsigned) image after verification. Deploy by
    **digest** (Chapter 10) so what you verified is exactly what runs. Tag + signature
    without digest pinning is a false sense of security.

!!! key "Generate an SBOM and attestation too"
    Beyond signing, produce a **Software Bill of Materials** (`syft`) and a **SLSA
    provenance attestation** describing *how* the image was built. Store them alongside the
    signature so that when the next Log4Shell drops, you can query which images contain the
    vulnerable component in seconds instead of days.


### 24.5 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - **etcd encryption at rest encrypts the value stored in etcd, not the transmission**: the kube-apiserver decrypts secrets when it reads them from etcd and re-encrypts when writing. Secret values flowing over the API server's TLS connection are in plaintext inside the API server's memory — a compromised API server process can still read all secrets.
    - **Cosign image signing verifies the image manifest digest**, not the image content. Two different images CAN have the same signed digest (preimage resistance of SHA-256 makes this computationally infeasible, but the trust is in the digest, not re-downloading and comparing bytes). The signature chain of trust is: registry push → Sigstore Rekor log entry → `cosign verify` at admission.
    - **`imagePullPolicy: IfNotPresent`** (the default for tagged images) means a pod restart on the same node re-uses the cached image WITHOUT re-verifying the Kyverno image signature policy. A signed image that is later found malicious will keep running on nodes that have the cached layer until the cache is cleared. Combine signature verification with periodic digest pin updates in your manifests.

!!! warning "Gotchas — traps that catch experienced engineers"
    - **KMS encryption key rotation**: when you rotate the KMS key used for etcd encryption, all existing Secrets must be rewritten to etcd with the new key (`kubectl get secrets --all-namespaces -o json | kubectl replace -f -`). Missing this step means some Secrets are still encrypted with the old key — and if the old key is revoked, those Secrets become permanently unreadable.
    - **Cosign keyless signing with Sigstore Fulcio** uses a short-lived OIDC certificate — the signing identity expires. If you rebuild and re-sign an image months later, the old signature is valid but the signing certificate is expired. `cosign verify` still passes (the transparency log records the original valid-time signature), but forensic tooling must handle this correctly.
    - **Trivy/Grype CVE database lag**: vulnerability scanners use a CVE database that may be hours to days behind the NVD feed. A scanner that shows "no CRITICAL CVEs" does not mean the image is safe — it means no KNOWN CRITICAL CVEs as of the last database update. Schedule daily scans, not just build-time scans.

!!! question "Architect Considerations"
    1. **Defense in depth for secrets**: encryption at rest (etcd KMS) + encryption in transit (TLS) + runtime access control (RBAC) + secret lifecycle management (Vault rotation) + audit logging (who accessed what secret when) are five independent layers. Implement all five — losing any one layer doesn't compromise the whole.
    2. **SBOM as a supply chain artefact**: generating an SBOM (`syft`) at build time and attaching it to the image (via cosign SBOM attestation) creates a persistent record of what went into the image. This is invaluable during a supply-chain incident: instead of rebuilding to check if a vulnerable library is present, query the SBOM.
    3. **Registry admission control**: configure the container registry to only accept pushes from CI/CD pipelines (not from developer laptops). Every image in the registry was built by a reproducible, audited pipeline. This is a preventive control that complements Kyverno's image verification.
    4. **Key management HSM integration**: the cosign private key should live in a Hardware Security Module (HSM) or cloud KMS, not on disk. A signing key on disk is as compromisable as any other file. Use Vault Transit Secrets Engine or AWS KMS as the cosign signing backend.
    5. **Incident response for a compromised image**: if a signed production image is found to contain a backdoor, what is your response playbook? Key steps: revoke the signature (add to Sigstore revocation list), identify all running instances (`kubectl get pods -o json | jq 'select(.spec.containers[].image == "...")'`), trigger emergency rolling update with a clean image, preserve forensic evidence. Pre-write this playbook before you need it.

!!! success "Chapter 24 checklist"
    - **EncryptionConfiguration** enabled for Secrets, ideally via a **KMS** provider.
    - Existing Secrets **re-encrypted** after enabling.
    - Images **signed** (cosign) and **verified at admission** (Kyverno), unsigned = denied.
    - Deploys pinned by **digest** so signatures are meaningful.
    - **SBOM + provenance** generated and stored for fast CVE response.

---
