# Publishing on GitHub

Nothing has been pushed. These steps publish the local repository once you are ready.

## Repository settings

- **Name:** `ot-sentinel-twin`
- **Description:** Physics-based OT/ICS anomaly detection on a synthetic industrial digital twin — explainable rules,
  incident investigation and deterministic replay. 100 % synthetic data.
- **Topics:** `cybersecurity` `ot-security` `ics-security` `digital-twin` `industrial-control-systems` `python` `react`
  `detection-engineering` `anomaly-detection` `blue-team` `security-monitoring`
- **Social preview:** `docs/screenshots/overview-incident.png`

## Steps (GitHub CLI)

```bash
gh auth login
gh repo create ot-sentinel-twin --public --source . --remote origin \
  --description "Physics-based OT/ICS anomaly detection on a synthetic industrial digital twin."
git push -u origin main
git push origin v0.1.0
gh repo edit --add-topic cybersecurity,ot-security,ics-security,digital-twin,industrial-control-systems,python,react,detection-engineering,anomaly-detection,blue-team,security-monitoring
gh release create v0.1.0 --title "OT Sentinel Twin v0.1.0" --notes-file docs/launch/RELEASE_NOTES_v0.1.0.md
```

Without the CLI: create an empty repository on github.com, then `git remote add origin <url>`, `git push -u origin main`
and `git push origin v0.1.0`, and draft the release from the tag using `docs/launch/RELEASE_NOTES_v0.1.0.md`.

## After the first push

1. Wait for **CI** and **CodeQL** to finish; fix anything environment-specific before announcing.
2. Enable *Private vulnerability reporting* (Settings → Code security) — `SECURITY.md` points to it.
3. Enable Dependabot alerts and security updates.
4. Replace `<your-account>` in `README.md` and `<REPOSITORY URL>` in `docs/launch/LINKEDIN.md`.
