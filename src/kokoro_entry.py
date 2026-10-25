"""Entry point for the standalone application and its background process."""
import multiprocessing
import sys


def main():
    multiprocessing.freeze_support()
    import kokoro_runtime as runtime
    runtime.configure_audio()
    if sys.argv[1:2] == ["--daemon"]:
        from kokoro_daemon import main as daemon
        daemon()
        return 0
    if sys.argv[1:2] == ["--menubar"] or (sys.platform == "darwin" and len(sys.argv) == 1):
        from kokoro_desktop import install_mac_services
        from kokoro_menubar import main as menubar
        install_mac_services()
        menubar()
        return 0
    from kokoro_cli import main as cli
    return cli()


if __name__ == "__main__":
    raise SystemExit(main())
