#!/usr/bin/env python3

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from SystemFunctions.cleaner import DeepCleaner
from TerminalDisplay.display import Cli


def main():
    cli = Cli()
    cli.show_header()

    cleaner = DeepCleaner(cli)
    summary = cleaner.run()

    cli.show_summary(summary)
    cli.show_recommendations(cleaner.get_recommendations(summary))


if __name__ == "__main__":
    main()
