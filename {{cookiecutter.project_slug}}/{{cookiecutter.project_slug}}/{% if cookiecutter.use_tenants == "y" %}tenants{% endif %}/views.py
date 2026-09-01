from __future__ import annotations
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django_tenants.utils import get_public_schema_name

from .forms import InvitationForm
from .forms import OrganizationCreateForm
from .models import Invitation
from .models import Tenant
from .services import create_invitation
from .services import send_invitation_notification


def _public_domain_redirect(request, tenant: Tenant):
    domain = tenant.domains.filter(is_primary=True).first()
    if not domain:
        return redirect("users:redirect")
    return redirect(f"{request.scheme}://{domain.domain}")


@login_required
def create_organization(request):
    if request.tenant.schema_name != get_public_schema_name():
        raise Http404
    if request.method == "POST":
        form = OrganizationCreateForm(request.POST, owner=request.user)
        if form.is_valid():
            with transaction.atomic():
                tenant = form.save()
                root_domain = settings.TENANT_USERS_DOMAIN.rstrip("/").split("://")[-1]
                root_domain = root_domain.split("/", 1)[0]
                tenant.domains.create(domain=f"{tenant.slug}.{root_domain}", is_primary=True)
            messages.success(request, _("Organization created successfully."))
            return _public_domain_redirect(request, tenant)
    else:
        form = OrganizationCreateForm(owner=request.user)
    return render(request, "tenants/organization_form.html", {"form": form})


@login_required
def invite_user(request):
    tenant = request.tenant
    if request.tenant.schema_name == get_public_schema_name() or tenant.owner_id != request.user.id:
        raise Http404
    if request.method == "POST":
        form = InvitationForm(request.POST, tenant=tenant, invited_by=request.user)
        if form.is_valid():
            invitation = form.save()
            try:
                send_invitation_notification(request, invitation)
            except Exception:
                messages.error(request, _("The invitation was created but could not be queued. Please try again."))
            else:
                messages.success(request, _("Invitation email queued."))
                return redirect("tenants:invite-user")
    else:
        form = InvitationForm(tenant=tenant, invited_by=request.user)
    pending_invitations = tenant.invitations.filter(
        status=Invitation.Status.PENDING,
    ).select_related("user")
    return render(
        request,
        "tenants/invite_user.html",
        {"form": form, "tenant": tenant, "pending_invitations": pending_invitations},
    )


@login_required
def resend_invitation(request, token):
    if request.method != "POST":
        raise Http404
    invitation = get_object_or_404(
        Invitation.objects.select_related("tenant", "user", "invited_by"),
        token=token,
    )
    if invitation.tenant.owner_id != request.user.id and not request.user.is_superuser:
        raise Http404
    if invitation.status != Invitation.Status.PENDING:
        messages.error(request, _("Only pending invitations can be resent."))
        return redirect("users:redirect")
    if invitation.is_expired:
        invitation.status = Invitation.Status.EXPIRED
        invitation.save(update_fields=["status", "updated_at"])
        messages.error(request, _("This invitation has expired."))
        return redirect("users:redirect")

    new_invitation = create_invitation(
        tenant=invitation.tenant,
        user=invitation.user,
        invited_by=request.user,
        message=invitation.message,
        expires_at=invitation.expires_at,
    )
    try:
        send_invitation_notification(request, new_invitation)
    except Exception:
        messages.error(request, _("A new invitation was created but could not be queued. Please try again."))
    else:
        messages.success(request, _("New invitation email queued."))
    return redirect("tenants:invite-user")


@login_required
def invitation_accept(request, token):
    invitation = get_object_or_404(
        Invitation.objects.select_related("tenant", "user"),
        token=token,
    )
    if invitation.user_id != request.user.id:
        raise Http404
    if request.method == "POST":
        try:
            invitation.accept()
        except ValidationError as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, _(f"You joined {invitation.tenant.name}."))
            return _public_domain_redirect(request, invitation.tenant)
    return render(request, "tenants/invitation_accept.html", {"invitation": invitation})


@login_required
def invitation_decline(request, token):
    if request.method != "POST":
        raise Http404
    invitation = get_object_or_404(Invitation, token=token)
    if invitation.user_id != request.user.id:
        raise Http404
    try:
        invitation.decline()
    except ValidationError as exc:
        messages.error(request, exc.message)
    else:
        messages.info(request, _("Invitation declined."))
    return redirect("users:redirect")
