"""Tests for building openfortivpn command line arguments."""

from __future__ import annotations

from core.command_builder import build_openfortivpn_command
from core.vpn_profile import VPNProfile


def test_build_command_for_saml_without_custom_port():
    profile = VPNProfile(
        name="saml-default",
        host="vpn.example.com",
        port=443,
        auth_type="saml",
    )

    command = build_openfortivpn_command(profile)

    assert command == [
        "openfortivpn",
        "vpn.example.com:443",
        "--saml-login",
    ]


def test_build_command_for_saml_with_custom_port():
    profile = VPNProfile(
        name="saml-custom",
        host="vpn.example.com",
        port=443,
        auth_type="saml",
        saml_port=8020,
    )

    command = build_openfortivpn_command(profile)

    assert command == [
        "openfortivpn",
        "vpn.example.com:443",
        "--saml-login=8020",
    ]


def test_build_command_for_password_with_username():
    profile = VPNProfile(
        name="password",
        host="vpn.example.com",
        port=443,
        auth_type="password",
        username="alice",
    )

    command = build_openfortivpn_command(profile)

    assert command == [
        "openfortivpn",
        "vpn.example.com:443",
        "--username=alice",
    ]
