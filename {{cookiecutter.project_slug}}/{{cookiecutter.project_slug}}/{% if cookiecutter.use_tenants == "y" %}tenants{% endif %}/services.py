from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import Invitation
from django.conf import settings
from django.urls import reverse

User = get_user_model()

def invitation_url(request, invitation: Invitation) -> str:
    path = reverse("tenants:invitation-accept", kwargs={"token": invitation.token})
    public_domain = settings.TENANT_USERS_DOMAIN
    if "://" in public_domain:
        base = public_domain.rstrip("/")
    else:
        scheme = request.scheme if request is not None else "https"
        base = f"{scheme}://{public_domain}"
    return f"{base}{path}"


def queue_invitation_notification(invitation: Invitation) -> None:
    """Queue invitation delivery after the current transaction commits."""
    from .tasks import send_invitation_email

    transaction.on_commit(lambda: send_invitation_email.delay(invitation.pk))


def send_invitation_notification(request, invitation: Invitation) -> None:
    """Backward-compatible entry point that queues, rather than sends, mail."""
    queue_invitation_notification(invitation)


@transaction.atomic
def create_invitation(*, tenant, email, invited_by, message="", expires_at=None):
    """Create a new invitation row, invalidating any older pending invitation."""
    Invitation.objects.filter(
        tenant=tenant,
        email=email,
        status=Invitation.Status.PENDING,
    ).update(status=Invitation.Status.CANCELED, updated_at=timezone.now())
    invitation = Invitation(
        tenant=tenant,
        email=email,
        invited_by=invited_by,
        message=message,
    )
    if expires_at is not None:
        invitation.expires_at = expires_at
    invitation.save()
    return invitation


def get_or_create_user_for_invitation(
    invitation: Invitation,
) -> tuple[User, bool]:
    """
    Return the user associated with an invitation email.

    Returns:
        (user, created)
    """
    email = invitation.email.strip().lower()

    user = User.objects.filter(email__iexact=email).first()

    if user is not None:
        return user, False

    # Create a user with no usable password.
    user = User(
        email=email,
        is_active=True,
    )
    user.set_unusable_password()
    user.save()

    return user, True


@transaction.atomic
def accept_invitation(invitation_id: int) -> tuple[Invitation, User, bool]:
    """
    Accept an invitation.

    Creates the user if the invitation email does not belong to an
    existing user, then adds the user to the tenant.

    Returns:
        (invitation, user, user_created)
    """
    invitation = (
        Invitation.objects
        .select_for_update()
        .select_related("tenant")
        .get(pk=invitation_id)
    )

    if invitation.status == Invitation.Status.ACCEPTED:
        user = User.objects.get(email__iexact=invitation.email)
        return invitation, user, False

    if invitation.status != Invitation.Status.PENDING:
        raise ValueError("This invitation is no longer available.")

    if invitation.is_expired:
        invitation.status = Invitation.Status.EXPIRED
        invitation.save(update_fields=["status", "updated_at"])
        raise ValueError("This invitation has expired.")

    user, created = get_or_create_user_for_invitation(invitation)

    

    if not user.is_active:
        raise ValueError("Your user account is inactive.")

    try:
        invitation.tenant.add_user(user)
    except Exception as exc:
        # Replace with ExistsError if that's the exact exception your
        # tenant_users package raises.
        raise ValueError(
            "You are already a member of this organization."
        ) from exc

    invitation.status = Invitation.Status.ACCEPTED
    invitation.accepted_at = timezone.now()
    invitation.save(
        update_fields=[
            "status",
            "accepted_at",
            "updated_at",
        ]
    )

    return invitation, user, created