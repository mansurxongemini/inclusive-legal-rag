# Security Policy

## Reporting a vulnerability

Please do not report security problems in public issues.

Report privately through GitHub: **Security → Report a vulnerability** on this repository. If that
option is unavailable, contact the maintainer on Telegram: [@mansurxonrustamov](https://t.me/mansurxonrustamov).

Include what you found, how to reproduce it and the impact you expect. You will get an acknowledgement,
and a fix or mitigation plan once the report is confirmed.

## Scope

Of particular interest:

- Bypasses of administrator authentication (`X-Admin-Key`, loopback detection) or API-key checks
- Prompt injection that makes the assistant ignore its grounding rules or leak configuration
- Server-side request forgery through the URL/file importers
- Exposure of user questions, feedback or conversation logs

## Deployment notes

- Set a strong `ADMIN_API_KEY`, and `ADMIN_LOOPBACK_ENABLED=false` behind a reverse proxy.
- Never commit `.env`; rotate any key that was ever committed or shared.
