"""Entry point for the standalone application and its background process."""
import multiprocessing
import os
import stat
import sys


def main():
    multiprocessing.freeze_support()
    # PyInstaller's Windows desktop launcher has no attached console.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    if sys.argv[1:2] == ["--capture-selection"]:
        from kokoro_selection import worker_main
        return worker_main()
    import kokoro_runtime as runtime
    runtime.configure_audio()
    if sys.argv[1:2] == ["--daemon"]:
        from kokoro_daemon import main as daemon
        daemon()
        return 0
    # Finder launches with /dev/null, whereas selection Services and shell
    # pipes supply a pipe or file. Those must reach the text-reading client.
    piped_input = False
    if sys.stdin is not None:
        try:
            mode = os.fstat(sys.stdin.fileno()).st_mode
            piped_input = stat.S_ISFIFO(mode) or stat.S_ISREG(mode)
        except (OSError, ValueError):
            pass
    if sys.argv[1:2] == ["--menubar"] or (sys.platform == "darwin" and len(sys.argv) == 1 and not piped_input):
        from kokoro_desktop import install_mac_services
        from kokoro_menubar import main as menubar
        install_mac_services()
        menubar()
        return 0
    from kokoro_cli import main as cli
    if len(sys.argv) == 1 and not piped_input:
        return cli(["--gui"])
    return cli()


if __name__ == "__main__":
    raise SystemExit(main())
