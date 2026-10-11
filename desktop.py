import sys
import time

if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()
    if len(sys.argv) == 3 and sys.argv[1] == "--startup-test":
        started = time.perf_counter()
        from paradigma_studio.startup import startup_test

        sys.exit(startup_test(sys.argv[2], started))
    elif len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        # Keep application imports inside the smoke test's exception handler so
        # missing native libraries produce a report instead of a GUI error dialog.
        from paradigma_studio.smoke import smoke_test

        sys.exit(smoke_test(sys.argv[2]))
    else:
        from paradigma_studio.app import main

        main()
