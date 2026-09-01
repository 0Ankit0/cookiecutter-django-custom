from __future__ import annotations
from typing import TYPE_CHECKING

from django.contrib import admin
from django.contrib import messages
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_tenants.admin import TenantAdminMixin
from unfold.admin import ModelAdmin

from .models import Domain
from .models import Invitation
from .models import Tenant
from .services import create_invitation
from .services import send_invitation_notification as queue_invitation
from .forms import InvitationAdminForm

@admin.register(Tenant)
class TenantAdmin(TenantAdminMixin, ModelAdmin):
    list_display = ["name", "schema_name", "owner", "created", "modified"]
    search_fields = ["name", "schema_name", "owner__email"]


@admin.register(Domain)
class DomainAdmin(ModelAdmin):
    list_display = ["domain", "tenant", "is_primary"]
    search_fields = ["domain", "tenant__name", "tenant__schema_name"]


@admin.register(Invitation)
class InvitationAdmin(ModelAdmin):
    form = InvitationAdminForm
    list_display = [
        "tenant",
        "email",
        "invited_by",
        "status",
        "expires_at",
        "sent_at",
    ]
    list_filter = ["status", "tenant"]
    search_fields = ["tenant__name", "email", "invited_by__email"]
    readonly_fields = [
        "token",
        "status",
        "invited_by",
        "sent_at",
        "accepted_at",
        "declined_at",
        "created_at",
        "updated_at",
    ]
    autocomplete_fields = ["tenant"]
    actions = ["send_invitation_notification"]

    @admin.action(description=_("Create and queue invitation notification"))
    def send_invitation_notification(self, request, queryset):
        queued = 0
        skipped = 0
        for invitation in queryset.select_related("tenant", "invited_by"):
            if invitation.status != Invitation.Status.PENDING or invitation.expires_at <= timezone.now():
                skipped += 1
                continue
            try:
                new_invitation = create_invitation(
                    tenant=invitation.tenant,
                    email=invitation.email,
                    invited_by=request.user,
                    message=invitation.message,
                    expires_at=invitation.expires_at,
                )
                queue_invitation(request, new_invitation)
                queued += 1
            except Exception as exc:  # pragma: no cover - broker dependent
                self.message_user(
                    request,
                    f"Could not queue {invitation}: {exc}",
                    level=messages.ERROR,
                )
        if queued:
            self.message_user(
                request,
                _(f"Created and queued {queued} new invitation notification(s)."),
                level=messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                _(f"Skipped {skipped} non-pending or expired invitation(s)."),
                level=messages.WARNING,
            )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.invited_by = request.user
        super().save_model(request, obj, form, change)

    def has_add_permission(self, request):
        return request.user.is_superuser and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser and super().has_delete_permission(request, obj)
