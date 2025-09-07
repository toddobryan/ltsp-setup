import shutil

from ltsp_setup import DATA_DIR, check_call

def add_ltsp_ppa():
    check_call(["add-apt-repository", "ppa:ltsp"])
    check_call(["apt", "update"])

def write_etc_hostname():
    hostname_file = DATA_DIR.joinpath("etc_hostname")
    check_call(["cp", hostname_file, "/etc/hostname"])
