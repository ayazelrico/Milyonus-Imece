"""TLS-protected SMTP login delivery."""
import os
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlencode


def send_login(email: str, token: str) -> None:
    message = EmailMessage()
    message["From"] = os.environ["MILYONUS_SMTP_FROM"]
    message["To"] = email
    message["Subject"] = "Milyonus sign in"
    url = os.environ["MILYONUS_WEB_PUBLIC_URL"].rstrip("/")
    if not url.startswith("https://"):
        raise ValueError("public login URL must use HTTPS")
    message.set_content(f"Sign in (expires in one hour): {url}/?{urlencode({'login_token': token})}")
    with smtplib.SMTP(os.environ["MILYONUS_SMTP_HOST"], int(os.environ.get("MILYONUS_SMTP_PORT", "587")), timeout=15) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        if os.environ.get("MILYONUS_SMTP_USER"):
            smtp.login(os.environ["MILYONUS_SMTP_USER"], os.environ["MILYONUS_SMTP_PASSWORD"])
        smtp.send_message(message)
