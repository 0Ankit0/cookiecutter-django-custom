from __future__ import annotations
from typing import TYPE_CHECKING

from django import forms
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from .models import Invitation
from .models import Tenant
from .services import create_invitation


User = get_user_model()


class OrganizationCreateForm(forms.ModelForm):
    class Meta:
        model = Tenant
        fields = ["name", "slug"]
        labels = {"slug": _("Subdomain")}
        help_texts = {"slug": _("Used as <subdomain>.<tenant domain>.")}

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
        self.fields["slug"].required = False

    def clean_slug(self):
        value = self.cleaned_data.get("slug") or self.cleaned_data.get("name")
        value = slugify(value)
        if not value:
            raise forms.ValidationError(_("Enter a valid organization name or subdomain."))
        schema_name = value.replace("-", "_")[:63]
        if (
            Tenant.objects.filter(slug=value).exists()
            or Tenant.objects.filter(schema_name=schema_name).exists()
        ):
            raise forms.ValidationError(_("That subdomain is already in use."))
        return value

    @transaction.atomic
    def save(self, commit=True):
        tenant = super().save(commit=False)
        tenant.owner = self.owner
        tenant.schema_name = self.cleaned_data["slug"].replace("-", "_")[:63]
        if commit:
            tenant.save()
            tenant.add_user(self.owner, is_superuser=True)
        return tenant


class InvitationAdminForm(forms.ModelForm):
    class Meta:
        model = Invitation
        fields = ["tenant", "email", "message"]

    def clean(self):
        cleaned = super().clean()
        tenant = cleaned.get("tenant")
        email = cleaned.get("email")
        if tenant and email and tenant.user_set.filter(email=email).exists():
            self.add_error("email", _("This user is already a member of the tenant."))
        return cleaned



class InvitationForm(forms.ModelForm):
    class Meta:
        model = Invitation
        fields = ["email", "message", "expires_at"]
        widgets = {
            "message": forms.Textarea(attrs={"rows": 4})
        }

    def __init__(self, *args, tenant=None, invited_by=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        self.invited_by = invited_by
        self.fields["email"].queryset = User.objects.filter(is_active=True).exclude(tenants=tenant)

    def clean_email(self):
        email = self.cleaned_data["email"]
        if self.tenant.user_set.filter(email=email).exists():
            raise forms.ValidationError(_("This user is already a member of the organization."))
        return email

    def save(self, commit=True):
        if not commit:
            return super().save(commit=False)
        return create_invitation(
            tenant=self.tenant,
            email=self.cleaned_data["email"],
            invited_by=self.invited_by,
            message=self.cleaned_data.get("message", ""),
            expires_at=self.cleaned_data.get("expires_at"),
        )
