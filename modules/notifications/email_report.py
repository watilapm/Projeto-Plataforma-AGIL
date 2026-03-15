import os
import smtplib
from email.message import EmailMessage


def _split_emails(valor: str):
    return [item.strip() for item in (valor or "").split(",") if item.strip()]


def enviar_relatorio_execucao(assunto: str, corpo_texto: str):
    """
    Envia e-mail via SMTP com credenciais de variaveis de ambiente.
    Retorna (enviado: bool, mensagem: str).
    """

    smtp_host = os.getenv("AGIL_SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("AGIL_SMTP_PORT", "587").strip())
    smtp_user = os.getenv("AGIL_EMAIL_USER", "").strip()
    smtp_password = os.getenv("AGIL_EMAIL_PASSWORD", "").strip()
    email_from = os.getenv("AGIL_EMAIL_FROM", smtp_user).strip()
    destinatarios = _split_emails(os.getenv("AGIL_EMAIL_TO", smtp_user))

    if not smtp_host:
        return False, "AGIL_SMTP_HOST nao definido"
    if not smtp_user or not smtp_password:
        return False, "AGIL_EMAIL_USER/AGIL_EMAIL_PASSWORD nao definidos"
    if not email_from:
        return False, "AGIL_EMAIL_FROM nao definido"
    if not destinatarios:
        return False, "AGIL_EMAIL_TO nao definido"

    mensagem = EmailMessage()
    mensagem["Subject"] = assunto
    mensagem["From"] = email_from
    mensagem["To"] = ", ".join(destinatarios)
    mensagem.set_content(corpo_texto)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(mensagem)

    return True, f"enviado para {', '.join(destinatarios)}"
