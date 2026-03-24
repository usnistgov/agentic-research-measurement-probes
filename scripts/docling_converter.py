"""Convert a PDF to Markdown using docling."""

import argparse

from docling.document_converter import DocumentConverter


def main():
    parser = argparse.ArgumentParser(description="Convert a PDF to Markdown using docling")
    parser.add_argument("input", help="Path to the input PDF file")
    parser.add_argument("output", help="Path to the output Markdown file")
    args = parser.parse_args()

    converter = DocumentConverter()
    result = converter.convert(args.input)
    print("  conversion done, dumping to markdown")
    txt = result.document.export_to_markdown()

    with open(args.output, "w") as f:
        f.write(txt)

    print(f"Text successfully extracted and saved to {args.output}")


if __name__ == "__main__":
    main()
