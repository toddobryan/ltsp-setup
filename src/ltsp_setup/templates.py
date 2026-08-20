"""Loading and filling in the text files we drop onto a machine.

Templates live in ``ltsp_setup/data`` and use :class:`string.Template`
syntax, so a placeholder looks like ``$NAME`` or ``${NAME}``.
"""

from __future__ import annotations

from importlib import resources
from string import Template
from typing import Mapping

DATA_PACKAGE = "ltsp_setup.data"


def read(name: str) -> str:
    """Return the raw text of a template."""
    return resources.files(DATA_PACKAGE).joinpath(name).read_text(encoding="utf-8")


def render(name: str, values: Mapping[str, object]) -> str:
    """Fill in a template.

    Raises:
        KeyError: If the template uses a placeholder that ``values`` lacks.
            This is deliberate: a silently half-filled config file is much
            worse to debug than a loud failure here.
    """
    text = Template(read(name))
    return text.substitute({k: str(v) for k, v in values.items()})
