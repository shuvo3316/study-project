"""Task 1: Download Tranco, select 500 domains, save and verify them."""

import csv
import io
import json
import random
import sqlite3
import ssl
import urllib.request
import zipfile
from pathlib import Path

import certifi
#install ---/usr/local/bin/python3 -m pip install certifi
# All files are saved beside this Python script.
FOLDER = Path(__file__).resolve().parent
DATA_FOLDER = FOLDER / "data"
DATABASE = FOLDER / "tranco_domains.db"
OUTPUT_CSV = FOLDER / "selected_domains.csv"

GROUP_WEIGHTS = [21.5, 18, 27.5, 14, 9.5, 4, 5.5]
CHUNK_SIZE = 70
SAMPLE_SIZE = 500


def download_tranco():
    """Download the latest Tranco list using verified HTTPS."""
    print("Step 1: Downloading Tranco list...")
    DATA_FOLDER.mkdir(exist_ok=True)

    # certifi supplies trusted CA certificates for Python on macOS.
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    api_url = "https://tranco-list.eu/api/lists/date/latest"
    request = urllib.request.Request(api_url, headers={"User-Agent": "StudyProject/1.0"})
    with urllib.request.urlopen(request, context=ssl_context, timeout=30) as response:
        information = json.load(response)

    list_id = information["list_id"]
    download_url = information["download"]
    request = urllib.request.Request(download_url, headers={"User-Agent": "StudyProject/1.0"})
    with urllib.request.urlopen(request, context=ssl_context, timeout=120) as response:
        downloaded_data = response.read()

    # Some Tranco download links return ZIP archives containing the CSV.
    if zipfile.is_zipfile(io.BytesIO(downloaded_data)):
        with zipfile.ZipFile(io.BytesIO(downloaded_data)) as archive:
            csv_files = [name for name in archive.namelist() if name.endswith(".csv")]
            if not csv_files:
                raise ValueError("The downloaded ZIP does not contain a CSV file.")
            downloaded_data = archive.read(csv_files[0])

    csv_path = DATA_FOLDER / f"tranco_{list_id}.csv"
    csv_path.write_bytes(downloaded_data)
    print("Downloaded list ID:", list_id)
    print("Saved to:", csv_path)
    return list_id, csv_path


def load_domains(csv_path):
    """Read and check the 1,000,000 ranked domains."""
    print("\nStep 2: Reading and validating domains...")
    domains = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        for row in reader:
            if not row:
                continue
            rank = int(row[0])
            domain = row[1].strip()
            if rank != len(domains) + 1 or not domain:
                raise ValueError(f"Unexpected Tranco ranking row: {row}")
            domains.append((rank, domain))

    if len(domains) != 1_000_000:
        raise ValueError(f"Expected 1,000,000 domains, found {len(domains)}")
    print("Validated domains:", len(domains))
    return domains


def select_domains(domains):
    """Select 500 distinct domains using the seven weighted groups."""
    print("\nStep 3: Sampling domains...")
    chunks = [domains[i:i + CHUNK_SIZE] for i in range(0, len(domains), CHUNK_SIZE)]

    # Divide the chunks into seven nearly equal-sized groups.
    groups = []
    start = 0
    for i in range(7):
        size = len(chunks) // 7
        if i < len(chunks) % 7:
            size += 1
        groups.append(chunks[start:start + size])
        start += size

    # A fixed seed makes the selection reproducible for the same Tranco list.
    random.seed(42)
    selected = {}  # domain -> (rank, group number)

    while len(selected) < SAMPLE_SIZE:
        group_index = random.choices(range(7), weights=GROUP_WEIGHTS, k=1)[0]
        chunk = random.choice(groups[group_index])
        rank, domain = random.choice(chunk)
        selected[domain] = (rank, group_index + 1)

    print("Chunks:", len(chunks))
    print("Groups:", len(groups))
    print("Unique selected domains:", len(selected))
    return selected


def save_and_verify(selected, domains, list_id):
    """Store the sample in SQLite, check it, and export a CSV."""
    print("\nStep 4: Saving SQLite database...")
    with sqlite3.connect(DATABASE) as connection:
        # This replaces the old sample, avoiding mixed data from different lists.
        connection.execute("DROP TABLE IF EXISTS domains")
        connection.execute("""
            CREATE TABLE domains (
                id INTEGER PRIMARY KEY,
                domain TEXT NOT NULL UNIQUE,
                tranco_rank INTEGER NOT NULL,
                group_number INTEGER NOT NULL
            )
        """)
        for domain, (rank, group_number) in selected.items():
            connection.execute(
                "INSERT INTO domains (domain, tranco_rank, group_number) VALUES (?, ?, ?)",
                (domain, rank, group_number),
            )
        rows = connection.execute(
            "SELECT domain, tranco_rank, group_number FROM domains ORDER BY tranco_rank"
        ).fetchall()

    print("\nStep 5: Verifying and exporting...")
    assert len(rows) == SAMPLE_SIZE, "Wrong number of domains"
    assert len({row[0] for row in rows}) == SAMPLE_SIZE, "Duplicate domains"
    for domain, rank, group_number in rows:
        assert domains[rank - 1] == (rank, domain), "Incorrect original rank"
        assert 1 <= group_number <= 7, "Incorrect group number"

    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["domain", "tranco_rank", "group_number", "tranco_list_id"])
        for domain, rank, group_number in rows:
            writer.writerow([domain, rank, group_number, list_id])

    print("All checks passed!")
    print("Database:", DATABASE)
    print("Exported CSV:", OUTPUT_CSV)


def main():
    list_id, csv_path = download_tranco()
    domains = load_domains(csv_path)
    selected = select_domains(domains)
    save_and_verify(selected, domains, list_id)
    print("\nTASK 1 COMPLETE")


if __name__ == "__main__":
    main()
