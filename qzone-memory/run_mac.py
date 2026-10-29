import sys
if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test-output':
        from qzone_memory.selftest import run
        run(sys.argv[2])
    else:
        from qzone_memory.mac_app import main
        main()
