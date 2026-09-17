# CSV report demo

Synthetic portfolio proof for a CSV merge/reporting offer. It is not prior customer work.

Requires Python 3.11 or later; no third-party packages.

Built by Tranced Media using AI-assisted development and runnable checks. For a custom reporting workflow, contact **creatorcontact@tranced.me** with a description and redacted examples. Scope and price are agreed before customer work begins.

```powershell
python .\csv_report_demo.py .\fixtures\input-a.csv .\fixtures\input-b.csv .\fixtures\input-c.csv -o merged.csv
python .\csv_report_demo.py --self-test
```

The script validates one to three compatible UTF-8 CSV inputs before creating a **new** output file. It keeps quoted multiline and Unicode fields intact, rejects malformed/incompatible input and invalid or non-finite `amount` values, and prints exact `Decimal` totals separately by currency.

The included synthetic fixtures produce this merged output:

```csv
name,amount,currency,note
Åse,1.10,DKK,"first line
second line"
李,2.20,DKK,"quoted, comma"
Mia,3.30,EUR,plain
```

Expected totals are `DKK: 3.30` and `EUR: 3.30`; currencies are never combined. Exact totals are supported up to 100 significant digits per addition, and inputs exceeding that limit are rejected before output creation.

It stores validated rows in memory and intentionally stops above 100,000 combined rows. Use a streaming implementation only when a real customer needs larger files.
