from ltsp_setup import DATA_DIR, check_call, write_to_file

NETPLAN_FILE = "/etc/netplan/ltsp.yaml"


def handle_networking(
    nic_for_internet: str,
    nic_for_ltsp: str,
    hostname: str,
    alt_hostnames: list[str],
    debug: bool,
) -> None:
    write_etc_hostname(hostname, debug)
    write_etc_hosts(hostname, alt_hostnames, debug)
    write_netplan(nic_for_internet, nic_for_ltsp, debug)
    check_call(["chmod", "go-r", NETPLAN_FILE], debug)
    check_call(["netplan", "apply"], debug)


def write_netplan(nic_for_internet: str, nic_for_ltsp: str, debug: bool):
    template_dict = {"ETH0": nic_for_internet, "ETH1": nic_for_ltsp}
    write_to_file("etc_netplan_ltsp.yaml", NETPLAN_FILE, template_dict, debug)


def write_etc_hostname(hostname: str, debug: bool) -> None:
    template_dict = {"HOSTNAME": hostname}
    write_to_file("etc_hostname.txt", "/etc/hostname", template_dict, debug)


def write_etc_hosts(hostname: str, alt_hostnames: list[str], debug: bool) -> None:
    template_dict = {"HOSTNAME": hostname, "ALT_HOSTNAMES": " ".join(alt_hostnames)}
    write_to_file("etc_hosts.txt", "/etc/hosts", template_dict, debug)


def add_ltsp_ppa():
    check_call(["add-apt-repository", "ppa:ltsp"])
    check_call(["apt", "update"])
