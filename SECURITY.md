# Security policy

## Supported versions

Only the latest release receives fixes. Update before reporting.

## Reporting

Do not open a public issue with exploitable details, tokens, keys, internal URLs or sensitive logs.

Use GitHub Security Advisories: https://github.com/arraisfilho/youtube-live-monitor/security/advisories/new. The report stays private until a fix is released.

Describe the impact, the smallest way to reproduce it and, if you have one, a suggested fix, without real credentials. Receipt is acknowledged within 7 days; the time to fix depends on severity.

## Secrets

Never publish:

- `secrets/app_key`: together with the database, it allows reading the YouTube API key
- the `app-data` volume (`state.db`): encrypted API key, password hash and sessions
- a YouTube Data API key
- production logs or backups

If a secret reaches Git, revoke it first. Removing it from the last commit does not remove it from published history.
