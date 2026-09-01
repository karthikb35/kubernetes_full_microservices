## <a name="ch23"></a>23. Runtime Threat Detection — Falco

RBAC, PSA, NetworkPolicy, and Kyverno are **preventive** — they stop bad things at admission or in the network. But some threats only appear **at runtime**: a compromised dependency spawns a shell, a container starts crypto-mining, an attacker reads `/etc/shadow`. **Falco** is the runtime security camera — it watches kernel activity live and alerts on suspicious behavior policies can't catch statically.

### 23.1 How Falco sees everything

![Falco](assets/diagrams/23-falco.png)

Falco runs as a **DaemonSet** (one pod per node, Chapter 11) with an **eBPF probe** in the kernel. It observes every **syscall** — process execution, file opens, network connections — and runs them against a **rules engine**. Matches become alerts routed to Slack, a SIEM, or Prometheus.

!!! mental "Mental model — a security camera vs. door locks"
    All the earlier chapters were **locks** — they stop the wrong people entering. Falco is
    the **CCTV + motion sensor** *inside* the building. Even if someone slips through a lock
    (a zero-day, a supply-chain compromise), Falco sees them do something they shouldn't —
    open the vault, climb through a vent — and raises the alarm in real time.

### 23.2 What Falco detects that nothing else can

| Behavior | Why static policy misses it |
|----------|----------------------------|
| **Shell spawned in a container** | The image was fine; the *runtime* behavior is the attack |
| Write to `/etc`, `/bin`, or SSH keys | Happens after admission |
| Unexpected outbound connection | Data exfiltration / C2 |
| Reading sensitive files (`/etc/shadow`) | Legit-looking process, illegit action |
| Container escape attempts | Kernel-level, invisible to the API server |

### 23.3 A Falco rule

Falco ships with a strong default ruleset; you extend it for TicketHub specifics:

```yaml
# repo/manifests/60-security/falco-rules.yaml (excerpt)
- rule: Shell spawned in TicketHub container
  desc: A shell was executed inside an application pod - likely compromise
  condition: >
    spawned_process and container
    and proc.name in (bash, sh, zsh, ash)
    and k8s.ns.name = "tickethub"
  output: >
    Shell in container (pod=%k8s.pod.name ns=%k8s.ns.name
    cmd=%proc.cmdline user=%user.name)
  priority: WARNING
  tags: [container, shell, mitre_execution]
```

```yaml
# Falco installed via Helm as a DaemonSet in the 'security' namespace (PSA privileged)
# with Falcosidekick forwarding alerts to Slack + Prometheus Alertmanager.
```

!!! key "Falco needs privileged access — isolate it"
    To read kernel syscalls Falco runs **privileged**, which is exactly what Chapter 20
    forbids for app pods. That's why it lives in a dedicated **`security`** namespace
    labeled PSA `privileged`, and why a Kyverno policy exempts only *that* namespace. The
    security tooling gets the access it needs, fenced off from everything else.

### 23.4 From alert to response

Detection is only useful if it drives action. Route Falco → **Falcosidekick** → your incident pipeline:

- **Slack/PagerDuty** — human alert for high-priority rules.
- **Prometheus/Alertmanager** — metrics + dashboards (Chapter 26).
- **SIEM** — long-term forensic storage.
- **Automated response** — e.g., a controller that cordons the node or kills the pod on a critical match.

!!! warning "Tune out the noise or the signal dies"
    Falco's defaults are chatty — a wall of alerts trains people to ignore all of them.
    Baseline your workloads, silence expected behavior (a legit init container that writes
    config), and reserve high-priority notifications for genuine threats. An untuned Falco
    is worse than none, because real alerts drown.


### 23.5 Nuances, Gotchas & Architect Considerations

!!! tip "Nuances — subtle behaviours to internalise"
    - **Falco rules are evaluated for every syscall event** on the node — there is a performance cost. Default Falco installs see 1-5% CPU overhead per node. Custom rules that add expensive string comparisons or regular expressions can push this higher. Profile rule performance with `falco --list-syscalls` and Falco's built-in stats output.
    - **`spawned_process` events fire for EVERY new process** — including shell commands run legitimately by init systems, healthchecks, and entrypoint scripts. A "shell spawned in container" rule without a trusted-container allowlist will generate enormous noise at cluster scale, causing alert fatigue. Tune allowlists carefully before enabling.
    - **Falco kernel module vs eBPF driver**: the kernel module gives full syscall coverage but requires `--privileged` and is blocked by secureboot. The eBPF driver is more portable and works with secureboot. Cilium also uses eBPF — ensure the eBPF programs don't conflict by checking kernel eBPF map limits (`ulimit -l`).

!!! warning "Gotchas — traps that catch experienced engineers"
    - **Falco rules are NOT NetworkPolicy**: Falco detects and alerts on suspicious activity; it does not block it. A Falco rule for "unexpected outbound connection" fires an alert but the connection proceeds. Combine Falco alerts with automated responses (Kubernetes admission webhook, Falco Sidekick → Kubernetes API to label/quarantine the pod) for actual blocking.
    - **Custom rule precedence**: Falco evaluates rules in file order. A custom rule file that overrides a default rule must use `override: { condition: replace }` explicitly. Silently adding a rule with the same name results in both rules firing, doubling the alert volume.
    - **Alert sink reliability**: Falco emits alerts to stdout by default. In a containerized deployment, this means alerts flow through the container log pipeline (Promtail → Loki). If Loki is down, alerts are lost. Always configure a Falco Sidekick integration with a durable sink (PagerDuty, Slack webhook, dedicated S3 bucket) for security-critical alerts.

!!! question "Architect Considerations"
    1. **Falco as the last line of defense**: Falco is a detective control — it observes and alerts but doesn't prevent. The order of security layers is: supply chain (Chapter 24) → image policy (Kyverno) → network policy (Chapter 21) → pod security (Chapter 20) → runtime detection (Falco). Each layer reduces the blast radius; Falco is what catches what the others miss.
    2. **Rule tuning vs alert fatigue trade-off**: too few rules = real attacks missed; too many rules = analyst fatigue and ignored alerts. Define a triage process: every new Falco alert type must have a runbook before the rule is enabled in production. Alerts without runbooks get disabled.
    3. **Incident response integration**: Falco Sidekick can trigger an Argo Workflow or a Kubernetes operator that automatically: labels the offending pod `status=quarantined`, applies a NetworkPolicy blocking all egress, and creates a PVC snapshot for forensics. Design this response automation before an incident occurs.
    4. **eBPF-based detection completeness**: Falco with eBPF driver captures syscall-level events. It cannot observe encrypted traffic payloads (TLS) or in-memory operations that don't make syscalls. For full observability of a compromised process, supplement Falco with memory forensics (LiME) or eBPF-based tracing (Tetragon by Cilium).
    5. **Compliance mapping**: Falco rules can be mapped to CIS Kubernetes Benchmark controls, NIST 800-53, or PCI-DSS requirements. Document which Falco rules satisfy which compliance controls — this makes audit preparation significantly faster.

!!! success "Chapter 23 checklist"
    - Falco runs as a **DaemonSet** (eBPF) on every node, in the isolated `security` ns.
    - Default ruleset enabled, **extended** with TicketHub-specific rules.
    - Alerts routed via **Falcosidekick** to Slack/SIEM/Prometheus.
    - Rules **tuned** to suppress known-good behavior — low false-positive rate.
    - A response path exists (page, and ideally auto-isolate on critical matches).

---
