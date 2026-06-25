from gemini_watermark_remover.paths import enable_high_dpi


def main() -> None:
    enable_high_dpi()
    from gemini_watermark_remover.app import run

    run()


if __name__ == '__main__':
    main()
