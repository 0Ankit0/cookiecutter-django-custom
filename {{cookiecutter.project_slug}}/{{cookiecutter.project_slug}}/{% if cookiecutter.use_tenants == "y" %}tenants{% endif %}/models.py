from __future__ import annotations
from typing import TYPE_CHECKING

from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_tenants.models import DomainMixin
from tenant_users.tenants.models import ExistsError
from tenant_users.tenants.models import TenantBase

if TYPE_CHECKING:
    pass

def default_invitation_expiry():
    return timezone.now() + timedelta(days=7)


class Tenant(TenantBase):
    """Project tenant metadata stored in the public schema."""

    name = models.CharField(_("Tenant Name"), max_length=255, unique=True)

    class Meta:
        verbose_name = _("Tenant")
        verbose_name_plural = _("Tenants")

    def __str__(self) -> str:
        return self.name


class Domain(DomainMixin):
    """Tenant domain mapping for host-based tenant routing."""

    class Meta:
        verbose_name = _("Domain")
        verbose_name_plural = _("Domains")


class Invitation(models.Model):
    """A pending request for a user to join a tenant."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        ACCEPTED = "accepted", _("Accepted")
        DECLINED = "declined", _("Declined")
        EXPIRED = "expired", _("Expired")
        CANCELED = "canceled", _("Canceled")

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField(_("Email address"))

    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=False,
        related_name="sent_tenant_invitations",
    )
    token = models.UUIDField(default=uuid4, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    message = models.TextField(blank=True)
    expires_at = models.DateTimeField(default=default_invitation_expiry)
    sent_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Tenant Invitation")
        verbose_name_plural = _("Tenant Invitations")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "email"],
                condition=Q(status="pending"),
                name="unique_pending_tenant_invitation",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"], name="tenants_inv_tenant__idx"),
            models.Index(fields=["email", "status"], name="tenants_inv_email_idx"),
            models.Index(fields=["expires_at"], name="tenants_inv_expires_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.email} → {self.tenant.name} ({self.get_status_display()})"

    @property
    def is_expired(self) -> bool:
        return self.status == self.Status.PENDING and self.expires_at <= timezone.now()

    def clean(self) -> None:
        super().clean()

        if (
            self.invited_by_id
            and not self.invited_by.is_superuser
            and self.tenant.owner_id != self.invited_by_id
        ):
            raise ValidationError(
                {
                    "invited_by": _(
                        "Only the tenant owner or a superuser can create invitations."
                    )
                }
            )

        if self.email:
            self.email = self.email.strip().lower()

        if self.tenant_id and self.email:
            # Don't allow inviting an email that already belongs to
            # a member of this tenant.
            if self.tenant.user_set.filter(
                email__iexact=self.email,
            ).exists():
                raise ValidationError(
                    {
                        "email": _(
                            "This email address already belongs to a member "
                            "of this organization."
                        )
                    }
                )

    @transaction.atomic
    def accept(self, user=None) -> None:
        invitation = (
            Invitation.objects
            .select_for_update()
            .select_related("tenant")
            .get(pk=self.pk)
        )

        if invitation.status == self.Status.ACCEPTED:
            return

        if invitation.status != self.Status.PENDING:
            raise ValidationError(
                _("This invitation is no longer available.")
            )

        if invitation.is_expired:
            invitation.status = self.Status.EXPIRED
            invitation.save(update_fields=["status", "updated_at"])
            raise ValidationError(
                _("This invitation has expired.")
            )

        if user is None:
            raise ValidationError(
                _("You must be logged in to accept this invitation.")
            )

        if not user.is_active:
            raise ValidationError(
                _("Your user account is inactive.")
            )

        if not user.email or user.email.casefold() != invitation.email.casefold():
            raise ValidationError(
                _("This invitation was sent to a different email address.")
            )

        try:
            invitation.tenant.add_user(user)
        except ExistsError as exc:
            raise ValidationError(
                _("You are already a member of this organization.")
            ) from exc

        invitation.status = self.Status.ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.save(
            update_fields=[
                "status",
                "accepted_at",
                "updated_at",
            ]
        )
        
    def decline(self) -> None:
        if self.status != self.Status.PENDING:
            raise ValidationError(_("This invitation is no longer available."))
        self.status = self.Status.DECLINED
        self.declined_at = timezone.now()
        self.save(update_fields=["status", "declined_at", "updated_at"])
