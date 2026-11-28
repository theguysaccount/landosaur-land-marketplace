"""Bundle EIA electricity prices, EIA-861 utility reports and BLS CPI-U."""
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
from .model import STATE_NAMES
from .net import FetchError, Fetcher

EIA_PAGE = "https://www.eia.gov/electricity/data/eia861/"
EIA_STATE_PRICE_PAGE = "https://www.eia.gov/electricity/annual/table.php?t=epa_02_10.html"
EIA_STATE_PRICE_XLSX = "https://www.eia.gov/electricity/annual/xls/epa_02_10.xlsx"
CPI_PAGE = "https://fred.stlouisfed.org/series/CPIAUCNS"
CPI_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCNS&cosd=2010-01-01"
COMMISSION_DIRECTORY = "https://www.naruc.org/about-naruc/our-mission/regulatory-commissions/"
COMMISSION_ROSTER = "https://maxxwww.naruc.org/forms/CompanyFormPublic/viewCommissionRoster?id="


def county_name(name):
    name = unicodedata.normalize("NFKD", name.casefold())
    name = name.encode("ascii", "ignore").decode()
    name = re.sub(r"\bsaint\b", "st", name)
    name = re.sub(r"\s+(county|parish|borough|census area|municipality)$", "", name)
    return re.sub(r"[^a-z0-9]", "", name)


def state_residential_prices(raw, year):
    from openpyxl import load_workbook

    states = {name: code for code, name in STATE_NAMES.items()}
    book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        rows = book["epa_02_10"].iter_rows(min_row=3, values_only=True)
        sectors, years = next(rows), next(rows)
        residential = sectors.index("Residential")
        column = next((i for i in (residential, residential + 1) if years[i] == f"Year {year}"), None)
        if column is None:
            raise ValueError(f"EIA Table 2.10 has no residential column for {year}")
        prices = {
            states[row[0].strip()]: round(row[column] / 100, 4)
            for row in rows
            if isinstance(row[0], str) and row[0].strip() in states
            and isinstance(row[column], (int, float)) and row[column] > 0
        }
    finally:
        book.close()
    if prices.keys() != STATE_NAMES.keys():
        raise ValueError("EIA Table 2.10 is missing state residential electricity prices")
    return prices


def commission_rosters(html):
    # Use the state IDs that drive the public NARUC map, including DC.
    section = re.search(r"var state_id = \{([^{}]+)\};\s*var commbyid", html)
    if not section or COMMISSION_ROSTER not in html:
        raise ValueError("NARUC roster links were not found")
    ids = dict(re.findall(r"\b([a-z]{2}): '([A-Z0-9]+)'", section[1]))
    if any(state.lower() not in ids for state in STATE_NAMES):
        raise ValueError("NARUC roster IDs are missing states")
    return {state: COMMISSION_ROSTER + ids[state.lower()] for state in STATE_NAMES}


def utility_dataset(raw, counties, year, state_prices):
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
    unmatched = set()

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for data_year, utility, name, state, owner in sheets("Utility_Data", "States", 3, 5):
            if data_year == year and isinstance(utility, int) and owner:
                ownership[utility] = owner

        for row in sheets("Sales_Ult_Cust", "States", 4, 11):
            data_year, utility, _, _, service_type, _, state, owner, _, revenue, sales = row
            if data_year != year or not isinstance(utility, int) or not isinstance(state, str):
                continue
            key = (state, utility)
            if owner:
                ownership[key] = owner
            if service_type == "Bundled" and isinstance(revenue, (int, float)) and isinstance(sales, (int, float)) and revenue > 0 and sales > 0:
                totals[key][0] += revenue
                totals[key][1] += sales

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
        "state_residential_usd_per_kwh": state_prices,
        "state_residential_source": EIA_STATE_PRICE_PAGE,
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
    parser.add_argument("--eia-state-xlsx", type=Path, help="Previously downloaded EIA Table 2.10 workbook")
    parser.add_argument("--cpi-csv", type=Path, help="Previously downloaded official FRED series")
    args = parser.parse_args()
    root = Path(config.DATA)
    fetch = Fetcher(max_bytes=35_000_000)
    archive_url = "%szip/f861%d.zip" % (EIA_PAGE, args.year)
    eia = args.eia_zip.read_bytes() if args.eia_zip else fetch.bytes(archive_url)
    state_prices = args.eia_state_xlsx.read_bytes() if args.eia_state_xlsx else fetch.bytes(EIA_STATE_PRICE_XLSX)
    cpi = args.cpi_csv.read_text() if args.cpi_csv else fetch.text(CPI_CSV)
    county_rows = json.loads((root / "usda" / "land-index-counties.json").read_text())
    utilities = utility_dataset(eia, county_rows, args.year, state_residential_prices(state_prices, args.year))
    utility_path = root / "utilities" / "county-utilities.json"
    try:
        utilities["state_commission_urls"] = commission_rosters(fetch.text(COMMISSION_DIRECTORY))
    except (FetchError, ValueError) as exc:
        print("NARUC directory refresh unavailable:", exc)
        if utility_path.exists():
            previous = json.loads(utility_path.read_text())
            utilities["state_commission_urls"] = previous.get("state_commission_urls", {})
    inflation = cpi_dataset(cpi)
    for dest, data in [
        (utility_path, utilities),
        (root / "market" / "cpi-u.json", inflation),
    ]:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
    print("EIA-861", args.year, len(utilities["utilities"]), "utility/state pairs across", len(utilities["counties"]), "counties")
    print("BLS CPI-U through", inflation["reference_year"], "month", inflation["reference_month"])


if __name__ == "__main__":
    main()
