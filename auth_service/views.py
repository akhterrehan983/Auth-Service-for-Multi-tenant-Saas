from django.contrib.auth import get_user_model, authenticate
from django.shortcuts import get_object_or_404
from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from .models import Organization, Member, Role
from .serializers import UserSerializer, OrganizationSerializer, MemberSerializer
from django.db import models  # Import models to use Count
from datetime import datetime
from django.utils.dateparse import parse_datetime
from django.utils.timezone import make_aware
from django.http import JsonResponse
import pytz

import os
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from django.conf import settings

User = get_user_model()


@api_view(["POST"])
def sign_up(request):
    user_data = request.data.get("user")
    org_data = request.data.get("organization")

    # Create User
    user_serializer = UserSerializer(data=user_data)
    if user_serializer.is_valid():
        user = user_serializer.save()
    else:
        return Response(user_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # Create Organization
    org_serializer = OrganizationSerializer(data=org_data)
    if org_serializer.is_valid():
        organization = org_serializer.save()
    else:
        return Response(org_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # Ensure Role 'Owner' exists or create it
    role, created = Role.objects.get_or_create(
        name="Owner",
        organization=organization,
        defaults={"description": "The owner of the organization."},
    )
    # Add User as a Member of the Organization with the Owner Role
    member = Member.objects.create(user=user, organization=organization, role=role)
    send_invite_email(user.email, organization.name)
    return Response(
        {
            "user": UserSerializer(user).data,
            "organization": OrganizationSerializer(organization).data,
            "role": role.name,
            "member_id": member.id,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
def sign_in(request):
    email = request.data.get("email")
    password = request.data.get("password")
    print(email, password)
    user = authenticate(email=email, password=password)
    if user is not None:
        refresh = RefreshToken.for_user(user)
        send_login_alert_email(email)
        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            }
        )
    return Response(
        {"error": "Authentication failed"}, status=status.HTTP_401_UNAUTHORIZED
    )


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def reset_password(request):
    user = request.user
    user.set_password(request.data["password"])
    user.save()

    # Send password update email
    send_password_update_email(user.email)

    return Response({"status": "password set"}, status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def invite_member(request):
    org_id = request.data.get("org_id")
    email = request.data.get("email")
    role_name = request.data.get("role")

    # Validate the organization exists
    organization = get_object_or_404(Organization, id=org_id)

    # Get or create the user by email
    user, created = User.objects.get_or_create(email=email)

    # Check if the user is already a member of this organization
    if Member.objects.filter(user=user, organization=organization).exists():
        return Response(
            {"error": "User is already a member of this organization"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Validate the role exists
    role = get_object_or_404(Role, name=role_name, organization=organization)

    # Create the member entry
    member = Member.objects.create(user=user, organization=organization, role=role)

    # Optionally send an email invitation to the user (if new)
    if created:
        send_invite_email(user.email, organization.name)

    return Response(MemberSerializer(member).data, status=status.HTTP_201_CREATED)


@api_view(["DELETE"])
@permission_classes([permissions.IsAuthenticated])
def delete_member(request, member_id):
    member = get_object_or_404(Member, id=member_id)
    member.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["PUT"])
@permission_classes([permissions.IsAuthenticated])
def update_member_role(request, member_id):
    member = get_object_or_404(Member, id=member_id)

    # Validate the role exists
    role = get_object_or_404(
        Role, name=request.data.get("role"), organization=member.organization
    )

    member.role = role
    member.save()
    return Response(MemberSerializer(member).data, status=status.HTTP_200_OK)


# 1. Role-wise Number of Users (with Filters)

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def role_wise_users(request):
    from_time = request.query_params.get("from", None)
    to_time = request.query_params.get("to", None)
    status_description = request.query_params.get("status", None)

    queryset = Member.objects.all()

    if from_time:
        from_datetime = parse_datetime(from_time)
        if not from_datetime:
            return JsonResponse(
                {"error": "Invalid from date format"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not from_datetime.tzinfo:
            from_datetime = make_aware(from_datetime)
        queryset = queryset.filter(created_at__gte=from_datetime)

    if to_time:
        to_datetime = parse_datetime(to_time)
        if not to_datetime:
            return JsonResponse(
                {"error": "Invalid to date format"}, status=status.HTTP_400_BAD_REQUEST
            )
        if not to_datetime.tzinfo:
            to_datetime = make_aware(to_datetime)
        queryset = queryset.filter(created_at__lte=to_datetime)

    # Status mapping with improved error handling
    status_map = {
        "active": 1,
        "inactive": 0,
        # Add more mappings as needed
    }

    if status_description:
        status_code = status_map.get(status_description.lower())
        if status_code is None:
            return JsonResponse(
                {"error": "Invalid status value"}, status=status.HTTP_400_BAD_REQUEST
            )
        queryset = queryset.filter(status=status_code)

    role_stats = (
        queryset.values("role__name")
        .annotate(count=models.Count("user"))
        .order_by("-count")
    )
    return Response(role_stats, status=status.HTTP_200_OK)


# 2. Organization-wise Role-wise Number of Users (with Filters)

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def org_role_wise_users(request):
    # Get filters from query parameters
    from_time = request.query_params.get("from", None)
    to_time = request.query_params.get("to", None)
    status_description = request.query_params.get("status", None)

    queryset = Member.objects.all()

    if from_time:
        from_datetime = parse_datetime(from_time)
        if not from_datetime:
            return JsonResponse({'error': 'Invalid from date format'}, status=status.HTTP_400_BAD_REQUEST)
        if not from_datetime.tzinfo:
            from_datetime = make_aware(from_datetime)
        queryset = queryset.filter(created_at__gte=from_datetime)

    if to_time:
        to_datetime = parse_datetime(to_time)
        if not to_datetime:
            return JsonResponse({'error': 'Invalid to date format'}, status=status.HTTP_400_BAD_REQUEST)
        if not to_datetime.tzinfo:
            to_datetime = make_aware(to_datetime)
        queryset = queryset.filter(created_at__lte=to_datetime)

    # Status mapping with improved error handling
    status_map = {
        "active": 1,
        "inactive": 0,
    }

    if status_description:
        status_code = status_map.get(status_description.lower())
        if status_code is None:
            return JsonResponse({'error': 'Invalid status value'}, status=status.HTTP_400_BAD_REQUEST)
        queryset = queryset.filter(status=status_code)

    org_role_stats = (
        queryset.values("organization__name", "role__name")
        .annotate(count=models.Count("user"))
        .order_by("-count")
    )
    return Response(org_role_stats, status=status.HTTP_200_OK)


#  3. Organization-wise Number of Members (without Filters)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def organization_wise_members(request):
    # Retrieve all members grouped by organization name and count them
    org_stats = (
        Member.objects.values("organization__name")
        .annotate(count=models.Count("user"))
        .order_by("-count")
    )
    return Response(org_stats, status=status.HTTP_200_OK)


# 1. Send Login Alert Email
def send_login_alert_email(email):
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = settings.BREVO_API_KEY

    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )

    # Define the email details
    sender = {"email": "akhterrehan983@gmail.com", "name": "Product Fusion"}
    to = [{"email": email}]
    subject = "New Login Alert"
    html_content = """
    <p>Hello,</p>
    <p>A login to your account was detected.</p>
    <p>If this wasn't you, please contact support immediately.</p>
    <p>Best regards,<br>Product Fusion</p>
    """

    # Create email object
    email_obj = sib_api_v3_sdk.SendSmtpEmail(
        sender=sender, to=to, subject=subject, html_content=html_content
    )

    try:
        # Send email
        api_response = api_instance.send_transac_email(email_obj)
        print(f"Email sent: {api_response}")
    except ApiException as e:
        print(f"Error sending email: {e}")


# 2. Send Password Update Email
def send_password_update_email(email):
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = settings.BREVO_API_KEY

    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )

    sender = {"email": "akhterrehan983@gmail.com", "name": "Product Fusion"}
    to = [{"email": email}]
    subject = "Password Update Notification"
    html_content = """
    <p>Hello,</p>
    <p>Your password has been successfully updated.</p>
    <p>If you did not perform this action, please contact support immediately.</p>
    <p>Best regards,<br>Product Fusion</p>
    """

    email_obj = sib_api_v3_sdk.SendSmtpEmail(
        sender=sender, to=to, subject=subject, html_content=html_content
    )

    try:
        api_response = api_instance.send_transac_email(email_obj)
        print(f"Email sent: {api_response}")
    except ApiException as e:
        print(f"Error sending email: {e}")


# 3. Send Invite Email
def send_invite_email(email, organization_name):
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = settings.BREVO_API_KEY

    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )

    sender = {"email": "akhterrehan983@gmail.com", "name": "Product Fusion"}
    to = [{"email": email}]
    subject = f"Invitation to Join {organization_name}"
    html_content = f"""
    <p>Hello,</p>
    <p>You have been invited to join {organization_name}.</p>
    <p>Please click the following link to accept the invitation and set up your account:</p>
    <a href="https://yourapp.com/invite">Accept Invitation</a>
    <p>Best regards,<br>Product Fusion</p>
    """

    email_obj = sib_api_v3_sdk.SendSmtpEmail(
        sender=sender, to=to, subject=subject, html_content=html_content
    )

    try:
        api_response = api_instance.send_transac_email(email_obj)
        print(f"Email sent: {api_response}")
    except ApiException as e:
        print(f"Error sending email: {e}")
