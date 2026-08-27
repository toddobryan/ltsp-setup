"""Template loading and substitution."""

from __future__ import annotations

import pytest

from ltsp_setup import templates


def test_missing_placeholder_fails_loudly() -> None:
    with pytest.raises(KeyError):
        templates.render("etc_hosts", {"HOSTNAME": "a"})


def test_hosts_file_gets_both_names() -> None:
    text = templates.render(
        "etc_hosts", {"HOSTNAME": "a.example.org", "ALT_HOSTNAMES": "a"}
    )
    assert "127.0.1.1       a.example.org a" in text


def test_rust_profile_keeps_literal_shell_variables() -> None:
    text = templates.render(
        "rust.sh",
        {"RUSTUP_HOME": "/usr/local/rustup", "CARGO_BIN": "/usr/local/cargo/bin"},
    )
    assert 'export RUSTUP_HOME="/usr/local/rustup"' in text
    assert "${PATH}" in text


def test_ltsp_conf_sets_default_image() -> None:
    text = templates.render(
        "ltsp.conf",
        {"DEFAULT_IMAGE": "ltsp-client-template", "LTSP_ADDRESS": "192.168.67.1"},
    )
    assert "[server]" in text
    assert 'DEFAULT_IMAGE="ltsp-client-template"' in text
    assert "NFS_HOME=1" in text


def test_ltsp_conf_applies_to_clients_not_the_server() -> None:
    text = templates.render(
        "ltsp.conf",
        {"DEFAULT_IMAGE": "ltsp-client-template", "LTSP_ADDRESS": "192.168.67.1"},
    )
    assert "[clients]" in text
    assert 'LIGHTDM_CONF="greeter-hide-users=true"' in text
    assert "ServerName 192.168.67.1" in text


def test_isolated_network_has_no_forward_or_ip_element() -> None:
    """No <forward/> means isolated; no <ip/> means libvirt runs no DHCP here.

    Parsed rather than string-matched, because the template explains both
    omissions in an XML comment.
    """
    from xml.etree import ElementTree

    xml = templates.render("network-ltsp.xml", {"NAME": "ltsp", "BRIDGE": "virbr-ltsp"})
    root = ElementTree.fromstring(xml)
    assert root.find("forward") is None
    assert root.find("ip") is None
    assert root.findtext("name") == "ltsp"
