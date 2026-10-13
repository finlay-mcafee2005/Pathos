"""
Transactional emails (welcome email on signup), sent through Resend's HTTP API.

Render's free plan blocks outbound SMTP, so we send over HTTPS instead.
Settings (Render -> Environment):
  RESEND_API_KEY   required to send; without it emails are skipped (logged)
  EMAIL_FROM       e.g. "Pathos <hello@pathosrun.com>" (domain verified in Resend)
  EMAIL_REPLY_TO   optional, where replies go (e.g. your forwarding address)
  APP_URL          link in the email, default https://pathosrun.com
"""

import html
import json
import logging
import os
import urllib.request

log = logging.getLogger("pathos.emails")

RESEND_URL = "https://api.resend.com/emails"
APP_URL = os.environ.get("APP_URL", "https://pathosrun.com").rstrip("/")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "Pathos <hello@pathosrun.com>")
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO") or None


def send_email(to: str, subject: str, html_body: str, text_body: str) -> bool:
    """Send one email. Never raises: a failed email must not break signup."""
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        log.info("RESEND_API_KEY not set; skipping email to %s", to)
        return False
    payload = {"from": EMAIL_FROM, "to": [to], "subject": subject, "html": html_body, "text": text_body}
    if EMAIL_REPLY_TO:
        payload["reply_to"] = EMAIL_REPLY_TO
    req = urllib.request.Request(
        RESEND_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                 "User-Agent": "Pathos/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = 200 <= resp.status < 300
            if not ok:
                log.warning("Email to %s failed: HTTP %s", to, resp.status)
            return ok
    except Exception as e:
        body = getattr(e, "read", lambda: b"")()
        log.warning("Email to %s failed: %s %s", to, e, body[:300] if body else "")
        return False


def welcome_email(full_name: str, verify_url: str = "") -> tuple:
    """(subject, html, text) for the signup welcome email."""
    first = (full_name or "").strip().split(" ")[0] or "there"
    name = html.escape(first)
    subject = "Welcome to Pathos 🏃"
    text = f"""Hi {first},

Thanks for signing up for Pathos! Your account is ready.
{"" if not verify_url else chr(10) + "Please verify your email: " + verify_url + chr(10) + "(The link works for 24 hours.)" + chr(10)}
Here's how it works:
1. Check in each day: energy, sleep, and anything sore. It takes about 30 seconds.
2. Get routes picked for how you feel, from 700+ routes around LA, Glendale and Pasadena.
3. Log your run, and Pathos learns what you like and how you recover.

Start your first check-in: {APP_URL}/checkin

Happy running,
Finlay, Pathos

You're getting this because you created a Pathos account with this email.
"""
    html_body = f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f4f6f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,Arial,sans-serif;color:#0b1220;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;padding:32px 12px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:20px;overflow:hidden;box-shadow:0 8px 28px rgba(11,108,235,.10);">
  <tr><td style="background:linear-gradient(120deg,#1d4ed8,#3b82f6);background-color:#2563eb;padding:28px 32px;">
    <table role="presentation" cellpadding="0" cellspacing="0"><tr>
      <td><img src="{APP_URL}/favicon.png" width="44" height="44" alt="" style="display:block;border-radius:12px;"></td>
      <td style="padding-left:12px;font-size:24px;font-weight:800;color:#ffffff;letter-spacing:-0.02em;">Pathos</td>
    </tr></table>
  </td></tr>
  <tr><td style="padding:32px 32px 8px;">
    <h1 style="margin:0 0 12px;font-size:26px;line-height:1.2;font-weight:800;letter-spacing:-0.02em;">Welcome, {name}!</h1>
    <p style="margin:0 0 20px;font-size:16px;line-height:1.55;color:#334155;">Thanks for signing up for Pathos. Your account is ready, and your first route is one quick check-in away.</p>
  </td></tr>
  {_verify_block(verify_url)}
  <tr><td style="padding:0 32px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      {''.join(f'''<tr><td style="padding:10px 0;vertical-align:top;width:40px;"><div style="width:30px;height:30px;border-radius:9px;background:#eaf1fe;color:#1d4ed8;font-weight:800;font-size:15px;line-height:30px;text-align:center;">{i}</div></td>
      <td style="padding:10px 0 10px 6px;font-size:15px;line-height:1.5;color:#334155;"><strong style="color:#0b1220;">{t}</strong><br>{d}</td></tr>''' for i, t, d in [
          (1, "Check in each day", "Energy, sleep and anything sore. About 30 seconds."),
          (2, "Get routes that fit today", "Picked from 700+ routes around LA, Glendale and Pasadena."),
          (3, "Log your run", "Pathos learns what you like and how you recover."),
      ])}
    </table>
  </td></tr>
  <tr><td align="center" style="padding:28px 32px 8px;">
    <a href="{APP_URL}/checkin" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;font-weight:700;font-size:16px;padding:14px 28px;border-radius:999px;">Start my first check-in &rarr;</a>
  </td></tr>
  <tr><td style="padding:24px 32px 32px;font-size:15px;line-height:1.55;color:#334155;">Happy running,<br><strong style="color:#0b1220;">Finlay</strong>, Pathos</td></tr>
</table>
<p style="max-width:560px;margin:16px auto 0;font-size:12px;line-height:1.5;color:#94a3b8;text-align:center;">You're getting this because you created a Pathos account with this email.<br><a href="{APP_URL}" style="color:#64748b;">pathosrun.com</a></p>
</td></tr></table>
</body></html>"""
    return subject, html_body, text


def send_welcome_email(to: str, full_name: str, verify_url: str = "") -> bool:
    subject, html_body, text = welcome_email(full_name, verify_url)
    return send_email(to, subject, html_body, text)


def _verify_block(verify_url: str) -> str:
    if not verify_url:
        return ""
    url = html.escape(verify_url, quote=True)
    return f"""<tr><td style="padding:0 32px 8px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef4ff;border-radius:16px;">
      <tr><td style="padding:18px 20px;font-size:15px;line-height:1.5;color:#1e3a8a;">
        <strong style="color:#0b1220;">One quick thing: verify your email.</strong><br>
        It keeps your account safe and lets you reset your password later.
        <div style="padding-top:14px;"><a href="{url}" style="display:inline-block;background:#ffffff;color:#1d4ed8;border:1.5px solid #2563eb;text-decoration:none;font-weight:700;font-size:15px;padding:10px 22px;border-radius:999px;">Verify my email</a></div>
        <div style="padding-top:10px;font-size:12px;color:#64748b;">The link works for 24 hours.</div>
      </td></tr>
    </table>
  </td></tr>"""


def verify_email(full_name: str, verify_url: str) -> tuple:
    """(subject, html, text) for a stand-alone "verify your email" message."""
    first = (full_name or "").strip().split(" ")[0] or "there"
    name = html.escape(first)
    url = html.escape(verify_url, quote=True)
    subject = "Verify your email for Pathos"
    text = f"""Hi {first},

Tap the link below to verify your email for Pathos:
{verify_url}

The link works for 24 hours. If you didn't ask for this, you can ignore this email.

Pathos
"""
    html_body = f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f4f6f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,Arial,sans-serif;color:#0b1220;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;padding:32px 12px;"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#ffffff;border-radius:20px;overflow:hidden;box-shadow:0 8px 28px rgba(11,108,235,.10);">
  <tr><td style="background:linear-gradient(120deg,#1d4ed8,#3b82f6);background-color:#2563eb;padding:24px 32px;">
    <table role="presentation" cellpadding="0" cellspacing="0"><tr>
      <td><img src="{APP_URL}/favicon.png" width="40" height="40" alt="" style="display:block;border-radius:11px;"></td>
      <td style="padding-left:12px;font-size:22px;font-weight:800;color:#ffffff;letter-spacing:-0.02em;">Pathos</td>
    </tr></table>
  </td></tr>
  <tr><td style="padding:30px 32px 6px;">
    <h1 style="margin:0 0 10px;font-size:24px;line-height:1.25;font-weight:800;">Verify your email, {name}</h1>
    <p style="margin:0;font-size:16px;line-height:1.55;color:#334155;">Tap the button to confirm this is your email. It keeps your account safe and lets you reset your password later.</p>
  </td></tr>
  <tr><td align="center" style="padding:26px 32px 10px;">
    <a href="{url}" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;font-weight:700;font-size:16px;padding:14px 30px;border-radius:999px;">Verify my email</a>
  </td></tr>
  <tr><td style="padding:10px 32px 30px;font-size:13px;line-height:1.5;color:#64748b;">The link works for 24 hours. If you didn't ask for this, you can ignore this email.</td></tr>
</table></td></tr></table>
</body></html>"""
    return subject, html_body, text


def send_verify_email(to: str, full_name: str, verify_url: str) -> bool:
    subject, html_body, text = verify_email(full_name, verify_url)
    return send_email(to, subject, html_body, text)
