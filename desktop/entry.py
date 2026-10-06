"""PyInstaller entry point; smoke test runs the packaged server without a GUI."""
import sys


def main():
    if len(sys.argv) == 3 and sys.argv[1] in ('--smoke-test', '--tunnel-smoke-test'):
        from desktop.smoke import run
        run(sys.argv[2], mode='tunnel' if sys.argv[1] == '--tunnel-smoke-test' else 'lan')
    else:
        from desktop.gui import main as launch
        launch()


if __name__ == '__main__':
    main()
