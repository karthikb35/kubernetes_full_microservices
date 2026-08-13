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

!!! success "Chapter 23 checklist"
    - Falco runs as a **DaemonSet** (eBPF) on every node, in the isolated `security` ns.
    - Default ruleset enabled, **extended** with TicketHub-specific rules.
    - Alerts routed via **Falcosidekick** to Slack/SIEM/Prometheus.
    - Rules **tuned** to suppress known-good behavior — low false-positive rate.
    - A response path exists (page, and ideally auto-isolate on critical matches).

---
