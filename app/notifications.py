# Copyright 2026 nullata/webui-manager
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import smtplib
import ssl
from email.mime.text import MIMEText

from .utils import decrypt_secret


logger = logging.getLogger(__name__)


def parse_recipients(raw: str | None) -> list[str]:
    """Split the stored To field into individual addresses. Accepts comma- or
    semicolon-separated lists and trims surrounding whitespace."""
    if not raw:
        return []
    return [addr.strip() for addr in raw.replace(";", ",").split(",") if addr.strip()]


def send_email(settings, subject: str, body: str) -> bool:
    recipients = parse_recipients(settings.smtp_to_address)
    if not settings.smtp_host or not settings.smtp_from_address or not recipients:
        logger.warning("Email not sent: SMTP not fully configured.")
        return False

    try:
        password = decrypt_secret(settings.smtp_password_encrypted) or ""
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from_address
        msg["To"] = ", ".join(recipients)

        # self-signed certs are common in homelabs - skip verification
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        # port 465 uses implicit SSL (SMTP_SSL); everything else starts plain
        implicit_ssl = not settings.smtp_use_starttls and settings.smtp_port == 465
        smtp_cls = smtplib.SMTP_SSL if implicit_ssl else smtplib.SMTP
        ctx_kwarg = {"context": ssl_ctx} if implicit_ssl else {}

        with smtp_cls(settings.smtp_host, settings.smtp_port, timeout=10, **ctx_kwarg) as smtp:
            if settings.smtp_use_starttls:
                smtp.starttls(context=ssl_ctx)
            if settings.smtp_username and password:
                smtp.login(settings.smtp_username, password)
            smtp.sendmail(settings.smtp_from_address, recipients, msg.as_string())

        return True
    except Exception:
        logger.exception("Failed to send email.")
        return False


def send_test_email(settings) -> bool:
    return send_email(
        settings,
        subject="webui-manager test email",
        body="This is a test email from webui-manager. Your SMTP configuration is working.",
    )


def send_down_alert(settings, webuis: list) -> bool:
    from datetime import datetime, timezone
    lines = []
    for webui in webuis:
        checked_at = webui.last_healthcheck_at or datetime.now(timezone.utc)
        lines.append(
            f"- {webui.name}\n"
            f"  URL:     {webui.url}\n"
            f"  Status:  {webui.last_healthcheck_status}\n"
            f"  Checked: {checked_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        )
    count = len(webuis)
    subject = f"[webui-manager] {count} service{'s are' if count != 1 else ' is'} DOWN"
    body = "The following services are unreachable:\n\n" + "\n".join(lines)
    return send_email(settings, subject, body)
