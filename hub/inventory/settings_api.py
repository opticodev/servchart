"""Settings API behind the in-app Settings page: manage hosts, users and your own password.

Everything except "my password" is admin-only (is_staff). Guards keep you from locking
yourself out: you can't remove your own admin rights, deactivate or delete yourself.
"""

import secrets

from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .audit import audit
from .graph import host_summary
from .models import Host
from .sso import sso_enabled

User = get_user_model()


def _forbidden(what="Only admins can do that."):
    return Response({"error": what}, status=status.HTTP_403_FORBIDDEN)


def _bad(msg):
    return Response({"error": msg}, status=status.HTTP_400_BAD_REQUEST)


def _password_errors(password, user=None):
    try:
        validate_password(password, user)
    except ValidationError as exc:
        return " ".join(exc.messages)
    return None


def user_summary(u) -> dict:
    return {
        "id": u.pk,
        "username": u.get_username(),
        "email": u.email,
        "is_staff": u.is_staff,
        "is_active": u.is_active,
        "sso": not u.has_usable_password(),  # created by single sign-on, no local password
        "last_login": u.last_login.isoformat() if u.last_login else None,
        "date_joined": u.date_joined.isoformat() if u.date_joined else None,
    }


# --- hosts --------------------------------------------------------------------------------


@api_view(["PATCH", "DELETE"])
def host_detail(request, pk: int):
    if not request.user.is_staff:
        return _forbidden()
    host = Host.objects.filter(pk=pk).first()
    if host is None:
        return Response({"error": "No such host."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "DELETE":
        if host.is_local:
            return _bad("This is the hub's own host; it would reappear on the next report. Remove the Docker socket from the hub to stop mapping it.")
        host.delete()
        audit(request, "host.delete", host.name)
        return Response(status=status.HTTP_204_NO_CONTENT)

    fields = []
    if "name" in request.data:
        name = str(request.data["name"]).strip()
        if not name or len(name) > 128:
            return _bad("A name (1-128 characters) is required.")
        if Host.objects.filter(name=name).exclude(pk=host.pk).exists():
            return _bad(f"A host named {name!r} already exists.")
        host.name = name
        fields.append("name")
    if "enabled" in request.data:
        host.enabled = bool(request.data["enabled"])
        fields.append("enabled")
    if fields:
        old_name = Host.objects.filter(pk=host.pk).values_list("name", flat=True).first()
        host.save(update_fields=fields)
        audit(request, "host.update", host.name, **({"renamed_from": old_name} if old_name != host.name else {}), enabled=host.enabled)
    return Response(host_summary(host))


# --- users --------------------------------------------------------------------------------


@api_view(["GET", "POST"])
def users(request):
    if not request.user.is_staff:
        return _forbidden()
    if request.method == "GET":
        return Response([user_summary(u) for u in User.objects.order_by("username")])

    username = str(request.data.get("username", "")).strip()
    if not username or len(username) > 150:
        return _bad("A username (1-150 characters) is required.")
    password = str(request.data.get("password") or "")
    generated = not password
    if generated:
        password = secrets.token_urlsafe(12)
    else:
        err = _password_errors(password, User(username=username))
        if err:
            return _bad(err)
    try:
        u = User.objects.create_user(
            username=username,
            email=str(request.data.get("email", "")).strip(),
            password=password,
            is_staff=bool(request.data.get("is_staff")),
        )
    except IntegrityError:
        return _bad(f"A user named {username!r} already exists.")
    u.is_superuser = u.is_staff
    u.save(update_fields=["is_superuser"])
    audit(request, "user.create", u.username, is_staff=u.is_staff)
    body = user_summary(u)
    if generated:
        body["password"] = password  # shown once
    return Response(body, status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
def user_detail(request, pk: int):
    if not request.user.is_staff:
        return _forbidden()
    u = User.objects.filter(pk=pk).first()
    if u is None:
        return Response({"error": "No such user."}, status=status.HTTP_404_NOT_FOUND)
    is_self = u.pk == request.user.pk

    if request.method == "DELETE":
        if is_self:
            return _bad("You can't delete your own account.")
        u.delete()
        audit(request, "user.delete", u.username)
        return Response(status=status.HTTP_204_NO_CONTENT)

    fields = []
    if "is_staff" in request.data:
        if is_self and not request.data["is_staff"]:
            return _bad("You can't remove your own admin rights.")
        u.is_staff = u.is_superuser = bool(request.data["is_staff"])
        fields += ["is_staff", "is_superuser"]
    if "is_active" in request.data:
        if is_self and not request.data["is_active"]:
            return _bad("You can't deactivate your own account.")
        u.is_active = bool(request.data["is_active"])
        fields.append("is_active")
    if "email" in request.data:
        u.email = str(request.data["email"]).strip()
        fields.append("email")
    if fields:
        u.save(update_fields=fields)
        audit(request, "user.update", u.username, is_staff=u.is_staff, is_active=u.is_active)
    return Response(user_summary(u))


@api_view(["POST"])
def user_reset_password(request, pk: int):
    """Set a new password for someone else. Without one in the body, a random one is generated."""
    if not request.user.is_staff:
        return _forbidden()
    u = User.objects.filter(pk=pk).first()
    if u is None:
        return Response({"error": "No such user."}, status=status.HTTP_404_NOT_FOUND)
    password = str(request.data.get("password") or "")
    generated = not password
    if generated:
        password = secrets.token_urlsafe(12)
    else:
        err = _password_errors(password, u)
        if err:
            return _bad(err)
    u.set_password(password)
    u.save(update_fields=["password"])
    if u.pk == request.user.pk:
        update_session_auth_hash(request, u)
    audit(request, "user.reset_password", u.username)
    return Response({"ok": True, **({"password": password} if generated else {})})


# --- me -----------------------------------------------------------------------------------


@api_view(["POST"])
def my_password(request):
    u = request.user
    if not u.has_usable_password():
        return _bad("Your account signs in through single sign-on; change your password there.")
    current = str(request.data.get("current_password") or "")
    new = str(request.data.get("new_password") or "")
    if not u.check_password(current):
        return _bad("Your current password is wrong.")
    err = _password_errors(new, u)
    if err:
        return _bad(err)
    u.set_password(new)
    u.save(update_fields=["password"])
    update_session_auth_hash(request, u)  # stay signed in
    audit(request, "me.password", u.username)
    return Response({"ok": True})


def me_payload(request) -> dict:
    from django.conf import settings

    u = request.user
    return {
        "id": u.pk,
        "username": u.get_username(),
        "email": u.email,
        "is_staff": u.is_staff,
        "sso_user": not u.has_usable_password(),
        "sso_enabled": sso_enabled(),
    }
