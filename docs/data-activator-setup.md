# Data Activator (Reflex) Guide

`azd up` deploys the baseline Reflex item automatically. The deployed item is
named `Surveillance Alerts` and contains four KQL-driven alert rules.

## What gets deployed

The current automation builds a Reflex definition from
[`data_activator/reflex_triggers.json`](../data_activator/reflex_triggers.json)
and posts it through the Fabric REST API.

| Rule | KQL source | Current cadence | Default action |
|------|------------|-----------------|----------------|
| Spoofing Alert | `detect_spoofing()` | 5 minutes | Teams message |
| Layering Alert | `detect_layering()` | 5 minutes | Teams message |
| Wash Trading Alert | `detect_wash_trading()` | 5 minutes | Teams message |
| Price And Volume Anomaly Alert | `detect_anomalies_advanced()` | 5 minutes | Teams message |

The notification recipient is resolved in this order:

1. `ACTIVATOR_ALERT_RECIPIENT`
2. `FABRIC_ADMIN_UPN`
3. The currently signed-in Azure user

## Verify the deployed Reflex item

1. Open [Microsoft Fabric](https://app.fabric.microsoft.com)
2. Navigate to workspace `mktsurveil-surveillance-<env>`
3. Open **Surveillance Alerts**
4. Confirm the four rules above are present
5. Run a simulation from the dashboard, then inspect the Reflex run history

> **Note:** The deployment creates the Reflex item and rule graph for you. No
> manual JSON import or portal-based authoring is required for the baseline path.

## Customize the rules

Edit [`data_activator/reflex_triggers.json`](../data_activator/reflex_triggers.json)
to change rule names, messages, KQL queries, or polling cadence.

The current builder supports:

- `alert_type: "teams"` for Teams messages
- `alert_type: "email"` for email notifications
- Fabric-supported polling intervals of 5, 15, 60, 180, 360, 720, or 1440 minutes

After updating the config, redeploy with either:

```bash
azd up
```

or just the Reflex step:

```bash
./scripts/deploy-activator.sh <workspace-id>
```

## Implementation files

- Builder: [`scripts/build_reflex_payload.py`](../scripts/build_reflex_payload.py)
- Deployment script: [`scripts/deploy-activator.sh`](../scripts/deploy-activator.sh)
- Trigger config: [`data_activator/reflex_triggers.json`](../data_activator/reflex_triggers.json)
- Tests: [`tests/test_reflex_payload.py`](../tests/test_reflex_payload.py)

## Current limitations

- The baseline deployment sends Teams or email notifications only; it does not
  provision webhook-based exchange or regulator integrations.
- Fabric anomaly detection models and Operations Agent are still optional,
  manual portal features.
- Python plugin enablement on Eventhouse remains a manual Fabric portal step.
