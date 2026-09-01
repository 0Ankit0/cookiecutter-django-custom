from django.urls import path

from . import views

app_name = "tenants"

urlpatterns = [
    path("organizations/new/", views.create_organization, name="organization-create"),
    path("organization/invite/", views.invite_user, name="invite-user"),
    path("organization/invite/<uuid:token>/resend/", views.resend_invitation, name="invitation-resend"),
    path("invitations/<uuid:token>/", views.invitation_accept, name="invitation-accept"),
    path("invitations/<uuid:token>/decline/", views.invitation_decline, name="invitation-decline"),
]
