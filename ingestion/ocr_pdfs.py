#!/usr/bin/env python3

import os

# CRITICAL: Stop Tesseract and underlying C++ libraries from CPU thrashing.
# This must be set before importing pytesseract or cv2.
os.environ["OMP_THREAD_LIMIT"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import re
import json
import argparse
import multiprocessing
import concurrent.futures
from pathlib import Path

import pytesseract
from pdf2image import convert_from_path
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Filename metadata parsing
# ---------------------------------------------------------------------------

MONTH_ABBR_MAP = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

MONTH_TO_SEASON = {
    1: "rabi",
    2: "rabi",
    3: "rabi",
    4: "zaid",
    5: "zaid",
    6: "kharif",
    7: "kharif",
    8: "kharif",
    9: "kharif",
    10: "kharif",
    11: "rabi",
    12: "rabi",
}


def parse_filename(filename: str) -> dict:
    """
    Extract month, year, season from SAU_TNAU filename patterns.
    """
    name_lower = filename.lower().replace(".pdf", "")

    # Find 4-digit year (20xx or 19xx)
    year_match = re.search(r"\b(20\d{2}|19\d{2})\b", name_lower)
    year = int(year_match.group()) if year_match else None

    # Find month name
    month_num = None
    month_name = None
    best_len = 0
    for abbr, num in MONTH_ABBR_MAP.items():
        if re.search(r"\b" + re.escape(abbr) + r"\b", name_lower):
            if len(abbr) > best_len:
                best_len = len(abbr)
                month_num = num
                month_name = abbr

    season = MONTH_TO_SEASON.get(month_num, "general")

    return {
        "source": filename,
        "month": month_name,
        "year": year,
        "season": season,
        "crop": "general",
        "soil_type": "general",
    }


# ---------------------------------------------------------------------------
# Parallelized OCR
# ---------------------------------------------------------------------------


def ocr_single_image(args):
    """
    Helper function for the ProcessPool to process a single image.
    """
    img, lang = args
    return pytesseract.image_to_string(img, lang=lang).strip()


def ocr_pdf(
    pdf_path: Path, lang: str = "tam+eng", dpi: int = 300, workers: int = None
) -> list[dict]:
    """
    Convert PDF to images and run Tesseract OCR using a ProcessPoolExecutor.
    """
    if workers is None:
        workers = multiprocessing.cpu_count()

    # Convert PDF to images
    images = convert_from_path(str(pdf_path), dpi=dpi, thread_count=workers)

    pages = []

    # Use ProcessPoolExecutor for true parallel execution without Python GIL interference
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        # Pass images and language to the helper function
        texts = list(executor.map(ocr_single_image, [(img, lang) for img in images]))

    for i, text in enumerate(texts):
        if text:
            pages.append({"page": i + 1, "text": text})

    return pages


# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------


def process_directory(
    input_dir: str, output_dir: str, lang: str, test_one: bool, workers: int
):
    # .expanduser() allows the use of '~' for home directory paths if needed
    input_path = Path(input_dir).expanduser()
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(input_path.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDFs found in {input_path}")
        return

    if test_one:
        pdf_files = pdf_files[:1]
        print(f"[test-one] Processing only: {pdf_files[0].name}")

    print(
        f"Found {len(pdf_files)} PDF(s) | Language: {lang} | DPI: 300 | Workers: {workers}\n"
    )

    failed = []
    for pdf_file in tqdm(pdf_files, desc="OCR progress", unit="pdf"):
        out_file = output_path / (pdf_file.stem + ".json")

        # Skip if already processed
        if out_file.exists():
            tqdm.write(f"  SKIP (already done): {pdf_file.name}")
            continue

        try:
            metadata = parse_filename(pdf_file.name)
            pages = ocr_pdf(pdf_file, lang=lang, workers=workers)

            if not pages:
                tqdm.write(f"  WARN: No text extracted from {pdf_file.name}")

            # Construct the final JSON payload
            result = {
                **metadata,
                "total_pages_with_text": len(pages),
                "pages": pages,
            }

            out_file.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tqdm.write(f"  OK  {pdf_file.name} → {len(pages)} page(s) extracted")

        except Exception as e:
            tqdm.write(f"  ERROR {pdf_file.name}: {e}")
            failed.append((pdf_file.name, str(e)))

    print(f"\n{'='*50}")
    print(f"Done. Output: {output_path.resolve()}/")
    if failed:
        print(f"\nFailed ({len(failed)}):")
        for name, err in failed:
            print(f"  {name}: {err}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fast ProcessPool OCR SAU/TNAU Tamil PDFs → JSON"
    )

    # Defaulting to your Windows D: drive paths
    parser.add_argument(
        "--input",
        default="/mnt/d/IISC/deepLearning/cropcompass/data/raw/SAU",
        help="Directory containing PDFs",
    )
    parser.add_argument(
        "--output",
        default="/mnt/d/IISC/deepLearning/cropcompass/data/raw/SAU_ocr_output",
        help="Directory for output JSON files",
    )
    parser.add_argument("--lang", default="tam+eng", help="Tesseract language")
    parser.add_argument(
        "--test-one",
        action="store_true",
        help="OCR only the first PDF as a sanity check",
    )

    # Automatically detect CPU cores, leaving one free
    default_workers = max(1, multiprocessing.cpu_count() - 1)
    parser.add_argument(
        "--workers",
        type=int,
        default=default_workers,
        help="Number of parallel processes",
    )

    args = parser.parse_args()

    process_directory(args.input, args.output, args.lang, args.test_one, args.workers)
