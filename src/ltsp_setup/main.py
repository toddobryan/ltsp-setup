import typer
from typing_extensions import Annotated

from ltsp_setup import common, server
from ltsp_setup.config import networking as net
from ltsp_setup.config import mirrors as mir

app = typer.Typer()


@app.command()
def handle_networking(
    nic_for_internet: Annotated[
        str, typer.Option(help="NIC connected to the internet")
    ] = net.nic_for_internet,
    nic_for_ltsp: Annotated[
        str, typer.Option(help="NIC connected to the LTSP clients")
    ] = net.nic_for_ltsp,
    hostname: Annotated[
        str, typer.Option(help="Fully qualified host name")
    ] = net.hostname,
    alt_hostnames: Annotated[
        list[str], typer.Option(help="Additional hostnames to attach to 127.0.1.1")
    ] = net.alt_hostnames,
    debug: Annotated[bool, typer.Option(help="False to actually run stuff")] = True,
) -> None:
    server.handle_networking(
        nic_for_internet, nic_for_ltsp, hostname, alt_hostnames, debug
    )


@app.command()
def update_mirrors_and_upgrade(
    mint_mirror: Annotated[str, typer.Option()] = mir.mint_mirror,
    mint_version: Annotated[str, typer.Option()] = mir.mint_version,
    mint_repos: Annotated[str, typer.Option()] = mir.mint_repos,
    ubuntu_mirror: Annotated[str, typer.Option()] = mir.ubuntu_mirror,
    ubuntu_version: Annotated[str, typer.Option()] = mir.ubuntu_version,
    ubuntu_repos: Annotated[str, typer.Option()] = mir.ubuntu_repos,
    ubuntu_security_mirror: Annotated[str, typer.Option()] = mir.ubuntu_security_mirror,
    debug: Annotated[bool, typer.Option(help="False to actually run stuff")] = True,
) -> None:
    common.update_mirrors_and_upgrade(
        mint_mirror,
        mint_version,
        mint_repos,
        ubuntu_mirror,
        ubuntu_version,
        ubuntu_repos,
        ubuntu_security_mirror,
        debug,
    )
