"""Export the trusted static explainer with its exact CSS for private offline use."""
from pathlib import Path

from . import private_fs

_STATIC = Path(__file__).resolve().parent / "static"
_CSS_LINK = '<link rel="stylesheet" href="/static/system-flow.css">'


def export_system_flow(output: Path) -> Path:
    """Write an equivalent inline-style export, rejecting symlink output paths."""
    output = private_fs.absolute(output)
    html = (_STATIC / "system-flow.html").read_text(encoding="utf-8")
    css = (_STATIC / "system-flow.css").read_text(encoding="utf-8")
    if html.count(_CSS_LINK) != 1:
        raise ValueError("Expected exactly one local system-flow CSS link")
    offline = html.replace(_CSS_LINK, "<style>\n" + css + "</style>", 1)
    private_fs.mkdir(output.parent)
    private_fs.write_text(output, offline)
    return output


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    export_system_flow(parser.parse_args().output)
