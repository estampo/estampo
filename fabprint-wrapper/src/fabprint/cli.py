"""Wrapper CLI that delegates to estampo with a deprecation warning."""

import sys


def main() -> None:
    print(
        "WARNING: 'fabprint' has been renamed to 'estampo'. "
        "Please run: pip install estampo && pip uninstall fabprint",
        file=sys.stderr,
    )
    from estampo.cli import main as estampo_main

    estampo_main()


if __name__ == "__main__":
    main()
