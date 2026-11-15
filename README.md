# Order-to-Cash - an FRP manufacturer's order book in SQL

A SQLite database of an order's journey from quotation to payment, for an FRP (fibreglass) manufacturer with three product lines - pressure vessels, pultrusion and grating - and 12 queries on it. In planning I follow orders from PO to dispatch every day, and a hand-kept register is often the only record of how work comes in.

All data is synthetic. No company's records, customer names or PO numbers are in this repo. The raw register is messy on purpose, the way a hand-kept register is.

**Skills:** SQL (CTEs, window functions, `EXISTS`, views), data cleaning with an audit log, validation checks.

## Most orders never had a quote

59.4% of orders came in as a repeat PO with no quotation. On vessels it is 76.8%.

| Product line | Quotes | Converted | Orders | Orders with no quote |
|---|---:|---:|---:|---:|
| Pressure Vessel | 64 | 65.6% | 181 | 76.8% |
| Pultrusion | 171 | 47.4% | 130 | 37.7% |
| Grating | 91 | 41.8% | 86 | 55.8% |

So `orders.quote_id` is often empty, and no query that counts or values orders inner-joins to quotations (Q1 uses `EXISTS`). An inner join would have dropped three fifths of the business without any error.

## Cleaning

The raw register is loaded with every column as text. `03_cleaning.sql` builds two views and writes every decision to `cleaning_log`: 21 entries covering 1,499 rows, the biggest being dates in three formats (499 rows) and promised dates taken from the PO (302).

- The register has the date 31-11-2024, which SQLite silently turns into 1 Dec 2024. So every date is converted and compared back, and anything that changes is flagged.
- "Open" can mean a live quote or an undelivered order. The 102 rows are split by whether they have a PO or job number (83 quotes, 19 orders), and the split is logged because it moves the conversion rate.

## Results

OTIF is 58.5% on 354 orders due (vessels 59.7%, grating 59.5%, pultrusion 56.2%), and "on time" is the problem: in full is 91.2%, on time only 61.0%.

Delay causes rank differently by count and by impact (Q5):
- most frequent: customer hold on drawing approval - 28 late orders, 24.1 days on average
- worst per order: dimensional rework after inspection - 4 orders, 53.8 days each
- biggest total: transport not arranged - 728 days across 21 orders

Revenue depends on very few customers.

| Line | Top customer | Top 1 share | Top 5 share | Customers with revenue |
|---|---|---:|---:|---:|
| Pultrusion | C0013 | 80.9% | 100.0% | 4 |
| Pressure Vessel | C0001 | 73.2% | 97.6% | 8 |
| Grating | C0020 | 57.0% | 88.5% | 19 |

₹24.7 m is outstanding and 70% of it is more than 90 days overdue (54 invoices, 12 customers), mostly with the same few big accounts (Q7).

LD is missing on most late orders: 121 of 138 (88%) have nothing in either LD column, so the penalty exposure in Q12 cannot be totalled.

## What I would do with this

1. Record the LD clause on every order.
2. Work on on-time delivery: book transport earlier and chase drawing approvals.
3. Chase the overdue invoices with the few big accounts first.

## How to run it

Needs SQLite 3.25 or later (macOS has it; check with `sqlite3 --version`).

```bash
sqlite3 o2c.db < 01_schema.sql
python3 02_generate_data.py
sqlite3 o2c.db < 03_cleaning.sql
sqlite3 o2c.db < 04_analysis_queries.sql
sqlite3 o2c.db < 05_validation_checks.sql
```

The data script uses only the Python standard library and a fixed seed, so the database is the same every time. The last command prints one row per check: 22 checks, 20 pass, 2 expected, 0 fail. Expected means the check found a data problem that was planted on purpose.

## What's in the repo

- `01_schema.sql` - 12 tables: customers, items, payment_terms, quotations, quotation_lines, orders, order_lines, dispatches, invoices, payments, raw_quote_register and cleaning_log
- `02_generate_data.py`, `raw_register.py`, `model_parameters.json` - generate the synthetic data
- `03_cleaning.sql` - the views `v_raw_register` and `v_otif`, and the cleaning log
- `04_analysis_queries.sql` - the 12 queries, each with its business question on top
- `05_validation_checks.sql` - the 22 checks
- `data_privacy_check.py` - scans every table and file for names, emails, phone numbers, GSTIN and PAN
- `o2c.db` - the built database
- `data/` - the raw register as CSV, query results, validation results and a log of the planted errors

## Assumptions

- About 70% of orders are set up to ship on time and 92% in full; each customer has one payment habit.
- 625 register rows, 1 Apr 2024 to 31 Aug 2026; USD-INR 83-90; GST 18%.
- Grating and pultrusion prices are public list prices from IndiaMART (Nov 2026), with up to 12% either way on each order line. There is no public price list for 1.4-3.0 m vessels, so vessel prices are an assumption, scaled up from a public price for a smaller vessel.
- No cost data, so nothing here is about margin.

## How this was made

I set the scope and the questions, brought the business knowledge (how orders, dispatches and payments run in a plant like this, and what a hand-kept register looks like) and reviewed the results. The Python that generates the data, the SQL and the first draft of this write-up were done with an AI assistant (Claude). The first version had unrealistic order quantities and prices; that was found in review and the data was rebuilt.
