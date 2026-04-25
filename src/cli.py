from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.etl.pipeline import DataIngestionPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="MSSP data ingestion and validation pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Load, validate, deduplicate, and save MSSP PUF data")
    ingest_parser.add_argument("--input", required=True, help="Input CSV or Excel file")
    ingest_parser.add_argument("--output", required=True, help="Output cleaned CSV file")
    ingest_parser.add_argument("--qa", required=True, help="Path to write QA report")

    disclosures_parser = subparsers.add_parser("disclosures", help="Ingest payer PA disclosure PDFs")
    disclosures_parser.add_argument("--dir", required=True, help="Directory containing disclosure PDFs")
    disclosures_parser.add_argument("--output", required=True, help="Output CSV file for extracted metrics")

    preview_parser = subparsers.add_parser("preview", help="Preview the MSSP PUF source data")
    preview_parser.add_argument("--input", required=True, help="Input CSV or Excel file")
    preview_parser.add_argument("--rows", type=int, default=10, help="Number of rows to preview")

    args = parser.parse_args()
    pipeline = DataIngestionPipeline()

    if args.command == "ingest":
        pipeline.run(Path(args.input), Path(args.output), Path(args.qa))
    elif args.command == "disclosures":
        from src.etl.disclosures import DisclosureIngestor
        ingestor = DisclosureIngestor()
        df = ingestor.ingest_directory(Path(args.dir))
        df.to_csv(args.output, index=False)
        logging.info(f"Saved disclosure metrics to {args.output}")
    elif args.command == "preview":
        preview_df = pipeline.preview(Path(args.input), args.rows)
        print(preview_df.to_csv(index=False))


if __name__ == "__main__":
    main()
