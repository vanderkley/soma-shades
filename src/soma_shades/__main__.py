def main() -> None:
    try:
        from soma_shades.cli import main as cli
    except ImportError:
        raise SystemExit("The soma command needs the bridge extra: pip install 'soma-shades[bridge]'") from None
    cli()


if __name__ == "__main__":
    main()
