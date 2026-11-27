"""Bundle EIA-861 utility reports and BLS CPI-U observations for local releases."""
import argparse
import collections
import csv
import datetime
import io
import json
from pathlib import Path
import re
import statistics
import unicodedata
import zipfile

from . import config
from .net import Fetcher

EIA_PAGE = "https://www.eia.gov/electricity/data/eia861/"
CPI_PAGE = "https://fred.stlouisfed.org/series/CPIAUCNS"
CPI_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCNS&cosd=2010-01-01"
COMMISSION_DIRECTORY = "https://www.naruc.org/about-naruc/our-mission/regulatory-commissions/"


def county_name(name):
    name = unicodedata.normalize("NFKD", name.casefold())
    name = name.encode("ascii", "ignore").decode()
    name = re.sub(r"\bsaint\b", "st", name)
    name = re.sub(r"\s+(county|parish|borough|census area|municipality)$", "", name)
    return re.sub(r"[^a-z0-9]", "", name)


def utility_dataset(raw, counties, year):
    from openpyxl import load_workbook

    keys = collections.defaultdict(set)
    for fips, name, state, *_ in counties:
        keys[(state, county_name(name))].add(fips)

    def sheets(name, tab, first, count):
        book = load_workbook(io.BytesIO(archive.read("%s_%d.xlsx" % (name, year))),
                             read_only=True, data_only=True)
        try:
            yield from book[tab].iter_rows(min_row=first, max_col=count, values_only=True)
        finally:
            book.close()

    service = collections.defaultdict(dict)
    utilities = {}
    ownership = {}
    totals = collections.defaultdict(lambda: [0.0, 0.0])
    state_totals = collections.defaultdict(lambda: [0.0, 0.0])
    unmatched = set()

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for data_year, utility, name, state, owner in sheets("Utility_Data", "States", 3, 5):
            if data_year == year and isinstance(utility, int) and owner:
                ownership[utility] = owner

        for row in sheets("Sales_Ult_Cust", "States", 4, 11):
            data_year, utility, name, _, service_type, quality, state, owner, _, revenue, sales = row
            if data_year != year or not isinstance(utility, int) or not isinstance(state, str):
                continue
            key = (state, utility)
            if owner:
                ownership[key] = owner
            if service_type == "Bundled" and isinstance(revenue, (int, float)) and isinstance(sales, (int, float)) and revenue > 0 and sales > 0:
                totals[key][0] += revenue
                totals[key][1] += sales
                state_totals[state][0] += revenue
                state_totals[state][1] += sales

        for data_year, utility, name, _, state, county in sheets("Service_Territory", "Counties_States", 2, 6):
            if data_year != year or not isinstance(utility, int) or not isinstance(county, str) or not name:
                continue
            county_key = (state, county_name(county))
            key = "%s:%d" % (state, utility)
            fips_codes = keys.get(county_key, ())
            if len(fips_codes) != 1:
                unmatched.add(county_key)
                continue
            fips = next(iter(fips_codes))
            service[fips][key] = name.strip()
            revenue, sales = totals[(state, utility)]
            utilities[key] = {
                "id": utility, "name": name.strip(), "ownership": ownership.get((state, utility), ownership.get(utility)),
                "residential_usd_per_kwh": round(revenue / sales, 5) if sales else None,
            }

    if len(service) < 2500 or len(utilities) < 1000:
        raise ValueError("EIA-861 workbook produced unexpectedly low county or utility coverage")
    return {
        "year": year, "source": EIA_PAGE, "state_commission_directory": COMMISSION_DIRECTORY,
        "counties": {code: sorted(providers, key=lambda k: providers[k].casefold()) for code, providers in service.items()},
        "utilities": utilities,
        "state_residential_usd_per_kwh": {state: round(revenue / sales, 5) for state, (revenue, sales) in state_totals.items()},
        "unmatched_county_names": len(unmatched),
    }


def cpi_dataset(raw):
    observations = collections.defaultdict(dict)
    for row in csv.DictReader(io.StringIO(raw)):
        if row["CPIAUCNS"] in ("", "."):
            continue
        date = datetime.date.fromisoformat(row["observation_date"])
        observations[date.year][date.month] = float(row["CPIAUCNS"])
    if not observations or min(observations) != 2010 or any(len(row) < 10 for y, row in observations.items() if y < max(observations)):
        raise ValueError("BLS CPI-U series is missing historical months")
    latest_year = max(observations)
    latest_month = max(observations[latest_year])
    return {
        "series": "CUUR0000SA0", "source": CPI_PAGE, "reference_year": latest_year,
        "reference_month": latest_month,
        "years": {year: {"mean": round(statistics.mean(points.values()), 5), "months": len(points)}
                  for year, points in sorted(observations.items())},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2025, help="Official final EIA-861 report year")
    parser.add_argument("--eia-zip", type=Path, help="Previously downloaded official report")
    parser.add_argument("--cpi-csv", type=Path, help="Previously downloaded official FRED series")
    args = parser.parse_args()
    root = Path(config.DATA)
    fetch = Fetcher(max_bytes=35_000_000)
    archive_url = "%szip/f861%d.zip" % (EIA_PAGE, args.year)
    eia = args.eia_zip.read_bytes() if args.eia_zip else fetch.bytes(archive_url)
    cpi = args.cpi_csv.read_text() if args.cpi_csv else fetch.text(CPI_CSV)
    county_rows = json.loads((root / "usda" / "land-index-counties.json").read_text())
    utilities = utility_dataset(eia, county_rows, args.year)
    inflation = cpi_dataset(cpi)
    for dest, data in [
        (root / "utilities" / "county-utilities.json", utilities),
        (root / "market" / "cpi-u.json", inflation),
    ]:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
    print("EIA-861", args.year, len(utilities["utilities"]), "utility/state pairs across", len(utilities["counties"]), "counties")
    print("BLS CPI-U through", inflation["reference_year"], "month", inflation["reference_month"])


if __name__ == "__main__":
    main()
