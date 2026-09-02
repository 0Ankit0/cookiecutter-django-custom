from django.dispatch import receiver
from django_tenants.signals import post_schema_sync

from .models import Tenant


@receiver(post_schema_sync, sender=Tenant)
def create_tenant_owner(sender, tenant, **kwargs):
    if not tenant.owner_id:
        return

    tenant.add_user(
        tenant.owner,
        is_superuser=True,
        is_staff=True
    )
