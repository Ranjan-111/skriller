# Local modifications

Initial copy preserves source files. Record patches in PROVENANCE.json.

SKR-093: `integrations/mcp_server.py` accepts optional trusted product handlers. Custom handlers skip host-wide configuration/doctor initialization and use product-side argument/error validation; default diagnostic behavior is unchanged. Tests cover the actual MCP SDK session, authenticated API/shared job ledger, workspace isolation and unchanged upstream doctor tests. File hash recorded in PROVENANCE.json.
