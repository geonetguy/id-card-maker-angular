# Entrypoint for `python -m idcard_maker` (used by `briefcase dev/run`)
from .app import main

if __name__ == "__main__":
    main().main_loop()
