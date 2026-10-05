"""Settings loading and override behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from ltsp_setup import config


def test_defaults_target_mint_22_3() -> None:
    settings = config.Settings()
    assert settings.mirrors.mint_version == "zena"
    assert settings.mirrors.ubuntu_version == "noble"


def test_ltsp_cidr_combines_address_and_prefix() -> None:
    net = config.Networking(ltsp_address="10.0.0.1", ltsp_prefix=16)
    assert net.ltsp_cidr == "10.0.0.1/16"


def test_ltsp_subnet_is_the_network_not_the_address() -> None:
    net = config.Networking(ltsp_address="10.0.5.1", ltsp_prefix=16)
    assert net.ltsp_subnet == "10.0.0.0/16"


def test_nfsd_threads_default_is_at_least_64() -> None:
    assert config.Settings().nfsd_threads >= 64


def test_toml_overrides_are_applied(tmp_path: Path) -> None:
    path = tmp_path / "ltsp-setup.toml"
    path.write_text(
        'admin_user = "teacher"\n'
        "\n[networking]\n"
        'hostname = "lab.example.org"\n'
        'alt_hostnames = ["lab", "lab2"]\n'
        "\n[mirrors]\n"
        'mint_version = "wilma"\n'
    )
    settings = config.load(path)
    assert settings.admin_user == "teacher"
    assert settings.networking.hostname == "lab.example.org"
    assert settings.networking.alt_hostnames == ("lab", "lab2")
    assert settings.mirrors.mint_version == "wilma"
    # Untouched settings keep their defaults.
    assert settings.mirrors.ubuntu_version == "noble"


def test_paths_in_toml_become_path_objects(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text('[lab]\npool_dir = "~/vms"\n')
    settings = config.load(path)
    assert isinstance(settings.lab.pool_dir, Path)
    assert "~" not in str(settings.lab.pool_dir)


def test_unknown_setting_is_rejected_with_a_helpful_message(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text('[mirrors]\nmint_verison = "zena"\n')
    with pytest.raises(ValueError, match="mint_verison"):
        config.load(path)


def test_bad_racket_source_is_rejected() -> None:
    with pytest.raises(ValueError, match="racket_source"):
        config.Apps(racket_source="snap")


def test_client_template_defaults_to_local_qcow2_disk() -> None:
    ct = config.Settings().client_template
    assert ct.connect_uri == "qemu:///system"
    assert ct.disk_path == Path("/var/lib/libvirt/images/ltsp-client-template.qcow2")


def test_client_template_toml_overrides_are_applied(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text(
        "[client_template]\n"
        'vm_name = "client-tmpl"\n'
        'disk_path = "/srv/vm/client.qcow2"\n'
        "disk_gb = 60\n"
    )
    settings = config.load(path)
    assert settings.client_template.vm_name == "client-tmpl"
    assert settings.client_template.disk_path == Path("/srv/vm/client.qcow2")
    assert settings.client_template.disk_gb == 60
    # Untouched settings keep their defaults.
    assert settings.client_template.network == "default"
