from __future__ import annotations
from typing import TYPE_CHECKING

from typing import Any

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.mail import EmailMultiAlternatives
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string


class InvitationEmailAdapter:
    """Render invitation mail using the same prefix/body pattern as allauth."""

    template_prefix = "tenants/email/tenant_invitation"

    def get_from_email(self) -> str:
        return settings.DEFAULT_FROM_EMAIL

    def format_email_subject(self, subject: str) -> str:
        prefix = getattr(settings, "TENANT_INVITATION_EMAIL_SUBJECT_PREFIX", "")
        return f"{prefix}{subject}" if prefix else subject

    def render_mail(
        self,
        email: str,
        context: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> EmailMessage:
        """Render text/HTML alternatives into a Django EmailMessage."""
        subject = render_to_string(
            f"{self.template_prefix}_subject.txt",
            context,
        )
        subject = " ".join(subject.splitlines()).strip()
        subject = self.format_email_subject(subject)

        bodies: dict[str, str] = {}
        for extension in ("html", "txt"):
            try:
                bodies[extension] = render_to_string(
                    f"{self.template_prefix}_message.{extension}",
                    context,
                ).strip()
            except TemplateDoesNotExist:
                if extension == "txt" and not bodies:
                    raise

        from_email = self.get_from_email()
        if "txt" in bodies:
            message = EmailMultiAlternatives(
                subject,
                bodies["txt"],
                from_email,
                [email],
                headers=headers,
            )
            if "html" in bodies:
                message.attach_alternative(bodies["html"], "text/html")
            return message

        message = EmailMessage(
            subject,
            bodies["html"],
            from_email,
            [email],
            headers=headers,
        )
        message.content_subtype = "html"
        return message

    def send_mail(
        self,
        email: str,
        context: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> int:
        message = self.render_mail(email, context, headers=headers)
        return message.send(fail_silently=False)
