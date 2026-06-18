import os
import time
import requests
from bs4 import BeautifulSoup
import pdfkit
from urllib.parse import urljoin, urlparse

# Set up the target and save locations
START_URL = "http://www.agritech.tnau.ac.in/agriculture/agri_index.html"
BASE_DIR = "http://www.agritech.tnau.ac.in/agriculture/"
SAVE_DIR = "data/raw/icar/"

# Ensure the directory exists
os.makedirs(SAVE_DIR, exist_ok=True)

# Important: If you are on Windows, you must point pdfkit to the installed executable.
# Uncomment and update this path if you get an "executable not found" error.
# path_wkhtmltopdf = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'
# config = pdfkit.configuration(wkhtmltopdf=path_wkhtmltopdf)
# For Linux/Mac, or if it's in your Windows PATH, use:
config = pdfkit.configuration()

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def get_subpage_links(start_url, base_dir):
    """Scrape the index page to find all relevant subpages."""
    print(f"Scanning index page: {start_url}...")
    try:
        response = requests.get(start_url, headers=HEADERS, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to access {start_url}: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    links = set()

    # Find all anchor tags
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_url = urljoin(start_url, href)

        # Only keep links that are within the /agriculture/ directory
        # and ignore links to entirely different domains or mailto links
        if full_url.startswith(base_dir) and full_url.endswith(".html"):
            # Ignore the index page itself
            if full_url != start_url:
                links.add(full_url)

    print(f"Found {len(links)} subpages to process.")
    return list(links)


def crawl_and_save_pdfs(links):
    """Visit each link and save the page as a PDF."""

    # PDF options to clean up the output slightly
    options = {
        "page-size": "A4",
        "margin-top": "0.75in",
        "margin-right": "0.75in",
        "margin-bottom": "0.75in",
        "margin-left": "0.75in",
        "encoding": "UTF-8",
        "no-outline": None,
        "quiet": "",  # Suppress verbose output in the terminal
    }

    success_count = 0

    for idx, url in enumerate(links, 1):
        # Create a clean filename from the URL
        parsed_url = urlparse(url)
        filename_base = os.path.basename(parsed_url.path).replace(".html", "")
        # Prepend SAU_TNAU so your retrieval engine knows the exact source origin
        pdf_filename = f"SAU_TNAU_{filename_base}.pdf"
        filepath = os.path.join(SAVE_DIR, pdf_filename)

        if os.path.exists(filepath):
            print(f"[{idx}/{len(links)}] Skipping {pdf_filename} - already exists.")
            continue

        print(f"[{idx}/{len(links)}] Converting {url} to PDF...")

        try:
            # pdfkit can convert a URL directly to a PDF
            # We pass the configuration and options defined above
            pdfkit.from_url(url, filepath, configuration=config, options=options)
            success_count += 1

            # Be polite to the TNAU servers
            time.sleep(2)

        except Exception as e:
            # Wkhtmltopdf often throws non-fatal errors (like missing images/CSS).
            # We catch them so the script doesn't completely crash.
            print(f"  -> Warning/Error generating {pdf_filename}: {e}")

    print(f"\nFinished! Successfully generated {success_count} PDFs in {SAVE_DIR}.")


# Execute the script
if __name__ == "__main__":
    target_links = get_subpage_links(START_URL, BASE_DIR)
    if target_links:
        crawl_and_save_pdfs(target_links)
