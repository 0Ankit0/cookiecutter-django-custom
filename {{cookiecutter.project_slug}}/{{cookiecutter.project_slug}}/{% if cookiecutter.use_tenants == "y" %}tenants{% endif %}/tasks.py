
from __future__ import annotations
from typing import TYPE_CHECKING

import logging
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .email import InvitationEmailAdapter
from .models import Invitation
from .services import invitation_url

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def send_invitation_email(self, invitation_id: int) -> bool:
    try:
        invitation = Invitation.objects.select_related(
            "tenant",
            "invited_by",
        ).get(pk=invitation_id)
    except Invitation.DoesNotExist:
        logger.warning(
            "Invitation %s does not exist",
            invitation_id,
        )
        return False

    if invitation.sent_at is not None:
        logger.info(
            "Invitation %s has already been sent",
            invitation.pk,
        )
        return True

    if invitation.status != Invitation.Status.PENDING:
        logger.info(
            "Invitation %s is not pending: %s",
            invitation.pk,
            invitation.status,
        )
        return False

    if invitation.expires_at <= timezone.now():
        invitation.status = Invitation.Status.EXPIRED
        invitation.save(update_fields=["status", "updated_at"])
        return False

    url = invitation_url(None, invitation)

    context = {
        "invitation": invitation,
        "tenant": invitation.tenant,
        "email": invitation.email,
        "invited_by": invitation.invited_by,
        "invitation_url": url,
        "expires_at": invitation.expires_at,
        "message": invitation.message,
    }

    logger.info(
        "Rendering invitation email for %s",
        invitation.email,
    )

    delivered = InvitationEmailAdapter().send_mail(
        invitation.email,
        context,
    )

    logger.info(
        "InvitationEmailAdapter returned %r",
        delivered,
    )

    if delivered != 1:
        raise RuntimeError(
            f"Invitation email backend returned {delivered}"
        )

    with transaction.atomic():
        updated = Invitation.objects.filter(
            pk=invitation.pk,
            sent_at__isnull=True,
            status=Invitation.Status.PENDING,
        ).update(
            sent_at=timezone.now(),
            updated_at=timezone.now(),
        )

    return bool(updated)