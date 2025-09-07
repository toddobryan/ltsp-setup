import textwrap

from ltsp_setup.config.mirrors import *
from ltsp_setup import check_call, logger

def update_mirrors_and_upgrade() -> None:
    logger.info(
        f"Setting mirrors to {mint_mirror} for Mint {mint_version} repos {mint_repos}, "
        + f"{ubuntu_mirror} and {ubuntu_security_mirror} for {ubuntu_version} repos {ubuntu_repos}"
    )
    cat_command = textwrap.dedent(
        f"""
            cat <<- EOF >/etc/apt/sources.list.d/official-package-repositories.list
            deb {mint_mirror} {mint_version} {mint_repos} 
    
            deb {ubuntu_mirror} {ubuntu_version} {ubuntu_repos}
            deb {ubuntu_mirror} {ubuntu_version}-updates {ubuntu_repos}
            deb {ubuntu_mirror} {ubuntu_version}-backports {ubuntu_repos}
    
            deb {ubuntu_security_mirror} {ubuntu_version}-security {ubuntu_repos}
            EOF"""
    ).strip()
    check_call(cat_command)
    logger.info("Done.")
    check_call(["apt", "update"])
    check_call(["apt", "upgrade", "-y"])
