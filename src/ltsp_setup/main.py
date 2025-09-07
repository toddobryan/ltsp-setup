import typer

from ltsp_setup import common

app = typer.Typer()

@app.command()
def update_mirrors_and_upgrade() -> None:
    common.update_mirrors_and_upgrade()
