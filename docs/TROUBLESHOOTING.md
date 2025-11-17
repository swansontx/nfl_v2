# Troubleshooting

Common issues and fixes

1. SSL certificate verification failures when using nfl_data_py
   - Symptom: Python ssl error: certificate verify failed: unable to get local issuer certificate
   - Fix:
     ```bash
     pip install --user certifi
     export SSL_CERT_FILE=$(python3 -c "import certifi; print(certifi.where())")
     ```
   - Re-run the script that failed (e.g., run_v5_models.py).

2. TheOddsAPI fetch returns empty or missing DraftKings markets
   - Symptom: player prop markets missing for DraftKings when snapshot is fetched
   - Fixes:
     - Remove the `markets` filter to fetch all markets and inspect the raw snapshot.
     - Poll the event with a safe backoff (5–10 min) until the markets appear.
     - Save snapshots with timestamps for post-mortem.

3. Mismatched player names / mapping failures
   - Symptom: many unmatched DK descriptions in unmatched CSV
   - Fix:
     - Ensure inputs/player_lookup_<YEAR>.json is built from nflverse-data release CSVs (stats_player_reg_<YEAR>.csv).
     - Run scripts/enrich_registry_with_nflverse.py to attach canonical ids and teams.
     - Tweak fuzzy matching threshold (script args) or manually add entries to models/player_registry.json.

4. Missing or incorrect registry file
   - Backup: models/player_registry.json.bak
   - To restore backup:
     ```bash
     mv models/player_registry.json.bak models/player_registry.json
     ```

5. OpenAI / LLM errors while running assistant scripts
   - Symptom: "Ran into this error: Request failed: error sending request for url (https://api.openai.com/v1/chat/completions)."
   - Fix:
     - Retry after a short delay (transient network issues are common).
     - Check network egress and API key validity. Add exponential backoff to calls.

6. Re-run models for a single event only
   - Use: `python3 scripts/run_v5_models.py` (script currently targets the Cowboys vs Raiders event by default; change EVENT_ID in script or pass an arg if you update it.)

Logs & diagnostics

- Main log file scanned: /Users/travisswanson/Documents/log.txt
- Short summary: /Users/travisswanson/Documents/LOG_SUMMARY.md
- Use the outputs/*.json and the cached snapshots in ~/.cache/goose/computer_controller for debugging mapping issues.

Contact

- Maintain backups of the registry and snapshots; if in doubt, ask the primary maintainer.
