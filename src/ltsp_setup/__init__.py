import logging
import subprocess
from pathlib import Path
from rich import print
from string import Template

logging.basicConfig(
    filename="/var/log/ltsp_setup.log",
    level=logging.INFO,
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger("ltsp-setup")


def check_call(command: str | list[str], debug: bool) -> None:
    if debug:
        cmd: str = " ".join(command) if type(command) is list else command  # type: ignore
        print(f"The following command would be run:\n{cmd}\n{'-' * 40}")
    else:
        logger.debug(f"Running command:\n{command}\n")
        try:
            subprocess.run(command, shell=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Command '{e.cmd}' failed with exit code {e.returncode}")


DATA_DIR = Path(__file__).absolute().parent.joinpath("data")


def sub_into_file(file_in_data_dir: str, template_dict: dict[str, str]) -> str:
    with open(DATA_DIR.joinpath(file_in_data_dir), "r") as f:
        src = Template(f.read())
        return src.substitute(template_dict)


def write_to_file(
    file_in_data_dir: str,
    path_to_write_to: str | Path,
    template_dict: dict[str, str],
    debug: bool,
) -> None:
    to_write = sub_into_file(file_in_data_dir, template_dict)
    if debug:
        print(f"Contents of {path_to_write_to}:")
        print("-" * 40)
        print(to_write)
        print("-" * 40)
    else:
        logger.info(
            f"Writing the contents of {file_in_data_dir} % {template_dict} "
            + "to {path_to_write_to}"
        )
        with open(path_to_write_to, "w") as f:
            f.write(to_write)
            logger.info("Done.")
