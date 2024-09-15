from django.urls import path
from . import views

urlpatterns = [
    path("signup/", views.sign_up, name="sign-up"),
    path("signin/", views.sign_in, name="sign-in"),
    path("reset_password/", views.reset_password, name="reset-password"),
    path("invite_member/", views.invite_member, name="invite-member"),
    path("delete_member/<int:member_id>/", views.delete_member, name="delete-member"),
    path(
        "update_member_role/<int:member_id>/",
        views.update_member_role,
        name="update-member-role",
    ),
    
    path("role_wise_users/", views.role_wise_users, name="invite-member"),
    path("org_role_wise_users/", views.org_role_wise_users, name="org-role-wise-users"),
    path(
        "organization_wise_members/",
        views.organization_wise_members,
        name="organization-wise-members",
    ),
]
