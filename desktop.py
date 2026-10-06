import sys

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        # Keep application imports inside the smoke test's exception handler so
        # missing native libraries produce a report instead of a GUI error dialog.
        from paradigma_desktop.smoke import smoke_test

        sys.exit(smoke_test(sys.argv[2]))
    else:
        from paradigma_desktop.app import main

        main()
