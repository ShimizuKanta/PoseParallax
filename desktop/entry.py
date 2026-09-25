"""PyInstaller entry point; smoke test runs the packaged server without a GUI."""
import sys


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--smoke-test':
        from desktop.smoke import run
        run(sys.argv[2])
    else:
        from desktop.gui import main as launch
        launch()


if __name__ == '__main__':
    main()
