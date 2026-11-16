"""SpendWise's AI on-call responder: advisory incident reports from bounded, read-only evidence.

Local, demo and CI only (compose.oncall.yaml; docs/observability.md, "AI on-call responder").
Standard library only. The pipeline, in order:

    signed POST /incidents (server.py, signing.py)
      → a validated spendwise.incident.v1 (incident.py)
      → evidence from Prometheus, Loki and Tempo through fixed query templates (evidence.py)
      → a fixed prompt with the evidence as delimited data (prompt.py)
      → a model's answer, validated against a strict schema and a content policy (model.py,
        analysis.py), or a deterministic fallback if it fails either
      → a spendwise.oncall.report.v1 in a bounded store (report.py, store.py)

It can't act: it makes GET requests to three fixed URLs and writes one file, and it runs without
credentials, a Docker socket or a route to the internet.
"""
