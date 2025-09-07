import logging
import subprocess
from pathlib import Path

logging.basicConfig(
    filename="/var/log/ltsp_setup.log",
    level=logging.INFO,
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger("ltsp-setup")

def check_call(command: str | list[str]) -> None:
    logger.debug(f"Running command:\n{command}\n")
    try:
        print(command)
        #subprocess.run(command, shell=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Command '{e.cmd}' failed with exit code {e.returncode}")

DATA_DIR = Path(__file__).absolute().parent.joinpath("data")