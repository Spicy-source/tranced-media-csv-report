#!/usr/bin/env python3
"""Merge compatible CSV files without changing the source data."""

from __future__ import annotations

import argparse
import csv
import tempfile
from decimal import Decimal, DecimalException, Inexact, InvalidOperation, Overflow, Rounded, localcontext
from pathlib import Path


# ponytail: rows stay in memory for simple validate-before-write behavior; stream only above this ceiling.
MAX_ROWS = 100_000
TOTAL_PRECISION = 100


class CsvError(ValueError):
    pass


def _header_index(headers: list[str], name: str) -> int | None:
    matches = [i for i, header in enumerate(headers) if header.casefold() == name]
    return matches[0] if len(matches) == 1 else None


def _read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            headers = next(reader, None)
            if not headers:
                raise CsvError(f"{path}: empty file")
            if any(not header.strip() for header in headers):
                raise CsvError(f"{path}: empty header")
            if len({header.casefold() for header in headers}) != len(headers):
                raise CsvError(f"{path}: duplicate header")
            rows: list[list[str]] = []
            for line_number, row in enumerate(reader, start=2):
                if len(row) != len(headers):
                    raise CsvError(f"{path}:{line_number}: expected {len(headers)} columns, got {len(row)}")
                rows.append(row)
                if len(rows) > MAX_ROWS:
                    raise CsvError(f"{path}: exceeds {MAX_ROWS:,} row in-memory ceiling")
            return headers, rows
    except UnicodeDecodeError as exc:
        raise CsvError(f"{path}: not valid UTF-8") from exc
    except csv.Error as exc:
        raise CsvError(f"{path}: malformed CSV: {exc}") from exc


def _totals(headers: list[str], rows: list[list[str]]) -> dict[str, Decimal]:
    amount_index = _header_index(headers, "amount")
    currency_index = _header_index(headers, "currency")
    if amount_index is None:
        return {}

    totals: dict[str, Decimal] = {}
    for row_number, row in enumerate(rows, start=2):
        raw_amount = row[amount_index].strip()
        try:
            amount = Decimal(raw_amount)
        except (InvalidOperation, ValueError) as exc:
            raise CsvError(f"row {row_number}: invalid amount {row[amount_index]!r}") from exc
        if not amount.is_finite():
            raise CsvError(f"row {row_number}: amount must be finite")
        currency = row[currency_index].strip() if currency_index is not None else "(no currency column)"
        if not currency:
            raise CsvError(f"row {row_number}: empty currency")
        try:
            with localcontext() as context:
                context.prec = TOTAL_PRECISION
                context.traps[Inexact] = True
                context.traps[Overflow] = True
                context.traps[Rounded] = True
                totals[currency] = totals.get(currency, Decimal("0")) + amount
        except DecimalException as exc:
            raise CsvError(f"row {row_number}: amount exceeds {TOTAL_PRECISION}-digit exact-total limit") from exc
    return totals


def merge(sources: list[Path], output: Path) -> dict[str, Decimal]:
    if not 1 <= len(sources) <= 3:
        raise CsvError("provide between 1 and 3 source CSV files")
    if output.exists():
        raise CsvError(f"output already exists: {output}")

    output_resolved = output.resolve()
    source_resolved = [source.resolve() for source in sources]
    if output_resolved in source_resolved:
        raise CsvError("output path must not alias a source path")

    header: list[str] | None = None
    all_rows: list[list[str]] = []
    for source in sources:
        if not source.is_file():
            raise CsvError(f"not a readable source file: {source}")
        source_header, rows = _read_csv(source)
        if header is None:
            header = source_header
        elif source_header != header:
            raise CsvError(f"incompatible headers: {source}")
        all_rows.extend(rows)
        if len(all_rows) > MAX_ROWS:
            raise CsvError(f"combined inputs exceed {MAX_ROWS:,} row in-memory ceiling")

    assert header is not None
    totals = _totals(header, all_rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(all_rows)
    except FileExistsError as exc:
        raise CsvError(f"output already exists: {output}") from exc
    return totals


def _expect_error(action) -> None:
    try:
        action()
    except CsvError:
        return
    raise AssertionError("expected CsvError")


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        sources = [root / f"source-{n}.csv" for n in range(1, 4)]
        for path, text in [
            (sources[0], 'name,amount,currency,note\nÅse,1.10,DKK,"first line\nsecond line"\n'),
            (sources[1], 'name,amount,currency,note\n李,2.20,DKK,"quoted, comma"\n'),
            (sources[2], 'name,amount,currency,note\nMia,3.30,EUR,plain\n'),
        ]:
            with path.open("w", encoding="utf-8", newline="") as handle:
                handle.write(text)
        output = root / "merged.csv"
        totals = merge(sources, output)
        with output.open("r", encoding="utf-8", newline="") as handle:
            rendered = list(csv.reader(handle, strict=True))
        assert rendered == [
            ["name", "amount", "currency", "note"],
            ["Åse", "1.10", "DKK", "first line\nsecond line"],
            ["李", "2.20", "DKK", "quoted, comma"],
            ["Mia", "3.30", "EUR", "plain"],
        ]
        assert totals == {"DKK": Decimal("3.30"), "EUR": Decimal("3.30")}
        _expect_error(lambda: merge([sources[0]], output))
        bad_output = root / "not-created.csv"
        malformed = root / "malformed.csv"
        malformed.write_text('name,amount,currency\na,1,DKK,extra\n', encoding="utf-8")
        _expect_error(lambda: merge([sources[0], malformed], bad_output))
        assert not bad_output.exists()
        incompatible = root / "incompatible.csv"
        incompatible.write_text('name,total,currency,note\na,1,DKK,x\n', encoding="utf-8")
        _expect_error(lambda: merge([sources[0], incompatible], root / "incompatible-out.csv"))
        duplicate = root / "duplicate.csv"
        duplicate.write_text('name,name\na,b\n', encoding="utf-8")
        _expect_error(lambda: merge([duplicate], root / "duplicate-out.csv"))
        empty_header = root / "empty-header.csv"
        empty_header.write_text('name,,currency\na,1,DKK\n', encoding="utf-8")
        _expect_error(lambda: merge([empty_header], root / "empty-header-out.csv"))
        blank_header_row = root / "blank-header-row.csv"
        blank_header_row.write_text("\n", encoding="utf-8")
        _expect_error(lambda: merge([blank_header_row], root / "blank-header-row-out.csv"))
        invalid_amount = root / "invalid-amount.csv"
        invalid_amount.write_text('name,amount,currency\na,NaN,DKK\n', encoding="utf-8")
        _expect_error(lambda: merge([invalid_amount], root / "invalid-amount-out.csv"))
        precision_loss = root / "precision-loss.csv"
        precision_loss.write_text(f'name,amount,currency\na,{"9" * 101},DKK\n', encoding="utf-8")
        _expect_error(lambda: merge([precision_loss], root / "precision-loss-out.csv"))
        _expect_error(lambda: merge([sources[0]], sources[0]))
    print("self-test passed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and merge 1-3 compatible UTF-8 CSV files.")
    parser.add_argument("sources", nargs="*", type=Path, help="1-3 source CSV files")
    parser.add_argument("-o", "--output", type=Path, help="new output CSV path")
    parser.add_argument("--self-test", action="store_true", help="run synthetic checks in a temporary directory")
    args = parser.parse_args()
    if args.self_test:
        if args.sources or args.output:
            parser.error("--self-test takes no sources or output")
        self_test()
        return
    if args.output is None:
        parser.error("--output is required")
    try:
        totals = merge(args.sources, args.output)
    except CsvError as exc:
        parser.error(str(exc))
    print(f"wrote {args.output}")
    if totals:
        for currency, total in totals.items():
            print(f"total {currency}: {total}")


if __name__ == "__main__":
    main()
