from ltsp_setup import check_call, logger, write_to_file


def update_mirrors_and_upgrade(
    mint_mirror: str,
    mint_version: str,
    mint_repos: str,
    ubuntu_mirror: str,
    ubuntu_version: str,
    ubuntu_repos: str,
    ubuntu_security_mirror: str,
    debug: bool,
) -> None:
    template_dict = {
        "MINT_MIRROR": mint_mirror,
        "MINT_VERSION": mint_version,
        "MINT_REPOS": mint_repos,
        "UBUNTU_MIRROR": ubuntu_mirror,
        "UBUNTU_VERSION": ubuntu_version,
        "UBUNTU_REPOS": ubuntu_repos,
        "UBUNTU_SECURITY_MIRROR": ubuntu_security_mirror,
    }
    write_to_file(
        "official-package-repositories.txt",
        "/etc/apt/sources.list.d/official-package-repositories.list",
        template_dict,
        debug,
    )
    check_call(["apt", "update"], debug)
    check_call(["apt", "upgrade", "-y"], debug)
