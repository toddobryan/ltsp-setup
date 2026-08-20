"""The generated netplan document."""

from __future__ import annotations

from typing import Any

import yaml

from ltsp_setup.config import Networking
from ltsp_setup.steps.server import netplan_config


def ethernets(net: Networking) -> dict[str, Any]:
    section: dict[str, Any] = netplan_config(net)["network"]["ethernets"]
    return section


def test_internet_nic_uses_dhcp_and_ltsp_nic_is_static() -> None:
    nics = ethernets(Networking())
    assert nics["enp1s0"]["dhcp4"] is True
    assert nics["enp2s0"]["dhcp4"] is False
    assert nics["enp2s0"]["addresses"] == ["192.168.67.1/24"]


def test_link_local_is_empty_so_pxe_clients_see_one_answer() -> None:
    for settings in ethernets(Networking()).values():
        assert settings["link-local"] == []


def test_macs_produce_match_and_set_name() -> None:
    net = Networking(
        mac_for_internet="52:54:00:67:00:01", mac_for_ltsp="52:54:00:67:00:02"
    )
    nics = ethernets(net)
    assert nics["enp1s0"]["match"] == {"macaddress": "52:54:00:67:00:01"}
    assert nics["enp1s0"]["set-name"] == "enp1s0"
    assert nics["enp2s0"]["match"] == {"macaddress": "52:54:00:67:00:02"}


def test_macs_are_lowercased() -> None:
    net = Networking(mac_for_internet="52:54:00:AB:CD:EF")
    assert ethernets(net)["enp1s0"]["match"]["macaddress"] == "52:54:00:ab:cd:ef"


def test_no_macs_means_no_match_block() -> None:
    nics = ethernets(Networking())
    assert "match" not in nics["enp1s0"]
    assert "set-name" not in nics["enp1s0"]


def test_disabled_nics_are_defined_but_off() -> None:
    nics = ethernets(Networking(nics_disabled=("enp3s0", "enp4s0")))
    assert nics["enp3s0"] == {"activation-mode": "off"}
    assert nics["enp4s0"] == {"activation-mode": "off"}


def test_off_is_quoted_so_yaml_does_not_read_it_as_false() -> None:
    document = yaml.safe_dump(netplan_config(Networking(nics_disabled=("enp3s0",))))
    assert "activation-mode: 'off'" in document
    reparsed = yaml.safe_load(document)
    assert reparsed["network"]["ethernets"]["enp3s0"]["activation-mode"] == "off"
