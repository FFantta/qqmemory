import sys

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test-output":
        from qqmemory.selftest import run

        run(sys.argv[2])
    else:
        from qqmemory.mac_app import main

        main()
