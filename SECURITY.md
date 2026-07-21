# Security policy

Thoughtstage is pre-alpha research software. Do not expose its local API or MCP
server directly to the public internet.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository. Do not
open a public issue containing secrets, exploit details, private experiment data,
or model credentials.

## Credential handling

Experiment manifests contain environment-variable names, never secret values.
Run bundles redact credential values by construction. Treat soliloquies and input
files as potentially sensitive research data even when the software itself is
open source.
