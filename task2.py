"""Study Project, Task 2: simple Tor relay statistics.

Run: python3 tor_statistics_easy.py
Needs: pip install stem matplotlib, and a Tor IPv4 geoip.txt file.
"""
import ssl
import certifi

import ipaddress
import tarfile
import urllib.request
from bisect import bisect_right
from collections import Counter
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path

import matplotlib.pyplot as plt
from stem.descriptor import parse_file

# ===== 1. SETTINGS =====
START = date(2026, 7, 26)
END = date(2026, 9, 23)
MONTHS = ["2026-07", "2026-08", "2026-09"]
BASE_URL = "https://collector.torproject.org/archive/relay-descriptors/consensuses/"
DATA_FOLDER = Path("stem_tar_data")
PLOT_FOLDER = Path("tor_plots")
CATEGORIES = ["neither", "guard_only", "exit_only", "guard_exit"]

DATA_FOLDER.mkdir(exist_ok=True)
PLOT_FOLDER.mkdir(exist_ok=True)


GEOIP_URL = (
    "https://gitlab.torproject.org/tpo/core/tor/"
    "-/raw/main/src/config/geoip"
)

# ===== 2. DOWNLOAD ARCHIVES (only if missing) =====
def download_archives():
    paths = []

    ssl_context = ssl.create_default_context(
        cafile=certifi.where()
    )

    for month in MONTHS:
        name = f"consensuses-{month}.tar.xz"
        path = DATA_FOLDER / name

        if path.is_file() and path.stat().st_size > 0:
            print("Already downloaded:", name)

        else:
            url = BASE_URL + name
            print("Downloading:", url)

            temporary = path.with_name(name + ".part")

            try:
                with urllib.request.urlopen(
                    url,
                    context=ssl_context,
                    timeout=120
                ) as response:

                    with temporary.open("wb") as file:
                        while True:
                            chunk = response.read(1024 * 1024)

                            if not chunk:
                                break

                            file.write(chunk)

                temporary.replace(path)
                print("Downloaded:", name)

            except Exception:
                temporary.unlink(missing_ok=True)
                raise

        paths.append(path)

    return paths


# ===== 3. LOAD GEOIP FILE =====
# geoip.txt is Tor's IPv4 GeoIP range file; place it beside this script.
# Its lines look like: start_number,end_number,country_code


def load_geoip():
    path = Path(__file__).resolve().parent / "geoip.txt"

    # Step 1: Download automatically if missing
    if not path.is_file() or path.stat().st_size == 0:
        print("GeoIP file missing. Downloading automatically...")

        ssl_context = ssl.create_default_context(
            cafile=certifi.where()
        )

        temporary = path.with_name("geoip.txt.part")

        try:
            with urllib.request.urlopen(
                GEOIP_URL,
                context=ssl_context,
                timeout=60
            ) as response:

                with temporary.open("wb") as file:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        file.write(chunk)

            temporary.replace(path)
            print("GeoIP downloaded successfully!")

        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    else:
        print("Using existing GeoIP file.")

    # Step 2: Load GeoIP ranges
    ranges = []

    with path.open(encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            first, last, country = line.split(",")

            ranges.append((
                int(first),
                int(last),
                country
            ))

    ranges.sort()
    starts = [item[0] for item in ranges]

    print("GeoIP ranges loaded:", len(ranges))

    return ranges, starts


def find_country(ip, ranges, starts):
    address = ipaddress.ip_address(ip)
    if address.version != 4:
        return "Unknown"
    number = int(address)
    position = bisect_right(starts, number) - 1
    if position >= 0:
        first, last, country = ranges[position]
        if first <= number <= last:
            return country
    return "Unknown"


# ===== 4. READ ALL CONSENSUSES =====
def read_consensuses(archives, ranges, starts):
    # One dictionary for each day. Each day contains sets and mappings.
    daily = {}

    for archive_path in archives:
        print("Reading:", archive_path)
        with tarfile.open(archive_path, "r:xz") as archive:
            members = sorted(
                [m for m in archive.getmembers() if m.isfile() and m.name.endswith("consensus")],
                key=lambda m: Path(m.name).name,
            )
           
            for member in members:
                day = datetime.strptime(Path(member.name).name[:10], "%Y-%m-%d").date()
                if day < START or day > END:
                    continue
                file = archive.extractfile(member)
                if file is None:
                    continue
                if day not in daily:
                    daily[day] = {
                        "all": set(), "valid_running": set(),
                        "stable": set(), "exit": set(),
                        "country": {}, "flags": {},
                    }
                info = daily[day]
                relays = parse_file(BytesIO(file.read()), descriptor_type="network-status-consensus-3 1.0")
                for relay in relays:
                    fp = relay.fingerprint
                    flags = set(relay.flags)
                    info["all"].add(fp)
                    if "Stable" in flags:
                        info["stable"].add(fp)
                    if "Exit" in flags and "BadExit" not in flags:
                        info["exit"].add(fp)
                    if "Valid" in flags and "Running" in flags:
                        info["valid_running"].add(fp)
                        # First Valid+Running observation fixes country and flags for that day.
                        if fp not in info["country"]:
                            info["country"][fp] = find_country(relay.address, ranges, starts)
                            info["flags"][fp] = flags
    return daily


# ===== 5. SMALL PLOT HELPER =====
def save_plot(dates, lines, title, filename, ylabel):
    plt.figure(figsize=(13, 7))
    for label, values in lines.items():
        plt.plot(dates, values, label=label, linewidth=1.5)
    plt.title(title)
    plt.xlabel("Date")
    plt.ylabel(ylabel)
    plt.grid(alpha=0.3)
    plt.xticks(rotation=45)
    plt.legend(loc="upper left", bbox_to_anchor=(1.02, 1), fontsize=7, ncol=3)
    plt.tight_layout()
    # plt.savefig(PLOT_FOLDER / filename, dpi=200, bbox_inches="tight")
    plt.show()
    plt.close()
    print("Saved:", filename)


# ===== 6. TASK 2(a): RELAY CHURN =====
def task_a(daily, dates):
    baseline = daily[START]["all"]
    ever_new = set()
    remaining, new_present, new_ever = [], [], []
    for day in dates:
        today = daily[day]["all"]
        new = today - baseline
        ever_new.update(new)
        remaining.append(len(today & baseline))
        new_present.append(len(new))
        new_ever.append(len(ever_new))
    save_plot(dates, {
        "Original relays still present": remaining,
        "New relays present": new_present,
        "Cumulative new relays": new_ever,
    }, "Task 2(a): Tor relay churn", "task_2a_churn.png", "Unique fingerprints")


# ===== 7. TASK 2(b): DAILY COUNTS =====
def task_b(daily, dates):
    lines = {}
    for label, key in [("All relays", "all"), ("Valid + Running", "valid_running"),
                       ("Stable", "stable"), ("Exit without BadExit", "exit")]:
        lines[label] = [len(daily[day][key]) for day in dates]
    save_plot(dates, lines, "Task 2(b): Daily relay counts", "task_2b_counts.png", "Unique fingerprints")


# ===== 8. TASK 2(c): COUNTRIES AND RELAY ROLES =====
def get_category(flags):
    guard = "Guard" in flags
    exit_flag = "Exit" in flags
    bad_exit = "BadExit" in flags
    if not guard and not exit_flag:
        return "neither"
    if guard and not exit_flag:
        return "guard_only"
    if exit_flag and not guard and not bad_exit:
        return "exit_only"
    if guard and exit_flag and not bad_exit:
        return "guard_exit"
    return None  # Exit + BadExit is excluded from usable Exit categories.


def task_c(daily, dates):
    # Store country percentages and percentages for each category in each country.
    country_shares = {}
    role_shares = {}
    all_countries = set()

    for day in dates:
        countries = daily[day]["country"]  # fingerprint -> country
        flags_by_fp = daily[day]["flags"]  # fingerprint -> flags
        totals = Counter(countries.values())
        if not totals:
            raise ValueError(f"No Valid+Running relays for {day}")
        all_countries.update(totals)
        role_counts = {country: Counter() for country in totals}
        excluded = 0

        for fp, country in countries.items():
            category = get_category(flags_by_fp[fp])
            if category is None:
                excluded += 1
            else:
                role_counts[country][category] += 1

        country_shares[day] = {}
        role_shares[day] = {}
        for country, count in totals.items():
            country_shares[day][country] = 100 * count / len(countries)
            role_shares[day][country] = {}
            for category in CATEGORIES:
                role_shares[day][country][category] = 100 * role_counts[country][category] / count

        if day == START:
            print("\nJuly 26 Valid+Running:", len(countries))
            print("Top 10 countries:", totals.most_common(10))
            for category in CATEGORIES:
                print(category + ":", sum(role_counts[c][category] for c in totals))
            print("Excluded Exit+BadExit:", excluded)

    all_countries = sorted(all_countries)
    lines = {}
    for country in all_countries:
        lines[country] = [country_shares[day].get(country, 0) for day in dates]
    save_plot(dates, lines, "Task 2(c): All country shares", "task_2c_countries.png", "% of worldwide Valid+Running relays")

    for category in CATEGORIES:
        lines = {}
        for country in all_countries:
            lines[country] = [role_shares[day].get(country, {}).get(category, 0) for day in dates]
        save_plot(dates, lines, "Task 2(c): " + category, "task_2c_" + category + ".png", "% within each country")


# ===== 9. RUN IN THIS ORDER =====
def main():
    archives = download_archives()
    ranges, starts = load_geoip()
    daily = read_consensuses(archives, ranges, starts)

    expected = {START + timedelta(days=i) for i in range((END - START).days + 1)}
    missing = sorted(expected - set(daily))
    print("Days found:", len(daily), "of", len(expected))
    if missing:
        raise ValueError(f"Missing dates: {missing}. Check whether the September archive is complete.")

    dates = sorted(daily)
    task_a(daily, dates)
    task_b(daily, dates)
    task_c(daily, dates)
    print("\nFinished! Graphs are in:", PLOT_FOLDER.resolve())


if __name__ == "__main__":
    main()
