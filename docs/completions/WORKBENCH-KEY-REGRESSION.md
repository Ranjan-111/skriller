# Submitted run display correction — 18 October 2026

The reported React warning was reproduced: the allowance and billing siblings used
the same signed-in account ID as their key. This violates React reconciliation's
identity contract. They now use separate allowance/billing namespaces; the run panel
also uses its own research namespace.

The two recent submissions matching the reported founder prompt had actually
completed, each retaining 17 unverified source results. No identity, source content,
token or credential was copied into this report. This is source discovery, not
evidence that those records are qualified founders.

The regression uses a workspace-backed submission, advances through completed
results and verifies visible source/download controls and absence of duplicate-key
warnings. Earlier workbench fixtures without workspace IDs did not exercise the
full account/result panel combination. The new warning assertion failed before
the production fix and passes after it.

Verification: 74 related workbench/results/billing checks pass; frontend typecheck
and diff whitespace checks pass. Current API readiness reports all dependencies
ready and the frontend returns HTTP 200. No model/key change, source dispatch,
browser session access or paid call was needed for the fix. The real Firebase
browser confirmation of this correction remains with the user after a hard refresh.
