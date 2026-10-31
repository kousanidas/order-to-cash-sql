# Order-to-Cash - an FRP manufacturer's order book in SQL

What happens to an order between the customer asking for a price and the money coming in? I built a small SQLite database of that journey for an FRP (fibreglass) manufacturer with three product lines - **pressure vessels, pultrusion and grating** - and wrote 12 analysis queries on it.

> **All data is synthetic.** No company's records, customer names or PO numbers are in this repo. I made the raw register messy on purpose - mixed date formats, two columns for the same thing, status words typed into the wrong column - because that is what a hand-kept register looks like.

**Skills used:** SQL (CTEs, window functions, `EXISTS`, views), data cleaning with an audit log, validation checks, Python to generate the data.

## Why I picked this

In planning I follow orders from PO to dispatch every day, and a hand-kept register is often the only record of how work comes in. It answers these questions badly:

- What share of quotes become orders, and does it differ by product line?
- How long from quote to order, and from order to delivery?
- Do we deliver on time and in full?
- How much is owed, and how overdue is it?
- Who pays late, and who actually makes up the revenue?
- What is sitting undelivered right now?
- How much work is lost or cancelled?

## The first surprise: most orders never had a quote

**59.4%** of orders came in as a repeat PO with no quotation behind them. On vessels it is **76.8%**.

| Product line | Quotes issued | Converted | Orders | Orders with no quote |
|---|---:|---:|---:|---:|
| Pressure Vessel | 64 | 65.6% | 181 | **76.8%** |
| Pultrusion | 171 | 47.4% | 130 | 37.7% |
| Grating | 91 | 41.8% | 86 | 55.8% |

This changed how I wrote the SQL. `orders.quote_id` can be empty, so no query that counts or values orders inner-joins to quotations. Q1 uses `EXISTS` instead. If I had inner-joined on `quote_id`, I would have dropped three fifths of the business without noticing, and every number after it would be wrong. This is the main reason I did this in SQL and not in a pivot table.

Q2 is the one place where an inner join is correct, because quote-to-PO time only exists for orders that had a quote. It prints its own count so you can see how many orders it covers.

It also means **conversion rate is not the right headline**. Only **161 of 397 orders (41%)** have a quote at all. The share of business coming in without a quote is more useful for a planner.

## Cleaning was most of the work

`raw_quote_register` is loaded with **every column as TEXT**, the way a spreadsheet exports it. `03_cleaning.sql` builds two views - `v_raw_register` (the cleaned register) and `v_otif` (the OTIF definition, kept in one place) - and writes every decision to `cleaning_log`. The raw table is never changed.

**21 entries covering 1,499 rows.** The ten biggest:

| What | Rows | Action |
|---|---:|---|
| Dates in three different text formats | 499 | PARSED |
| Promised date taken from the PO, not the register | 302 | FILLED |
| `Vertical` mixes two unrelated lists | 236 | FLAGGED |
| No value on an order row | 163 | FLAGGED |
| `Open` means two different things | 102 | MAPPED |
| Status word typed into the quote-number column | 57 | FLAGGED |
| `LD` and `LD Clause` - two columns for one thing | 42 | MAPPED |
| Status: 25 wordings mapped to 10 states | 25 | MAPPED |
| `LD` holds a delivery month, not a clause | 22 | FLAGGED |
| Register says Domestic, customer master says export | 15 | FLAGGED |

The other eleven entries cover 36 rows, for example orders with no delivery date agreed at all (8, excluded), free-text dates, an impossible calendar date and a PO dated 2205.

**The date check I'm glad I added.** One date in the register is **31-11-2024**. November has 30 days. SQLite does not reject it - `date('2024-11-31')` gives back `2024-12-01`. So every date is parsed, passed through `date()` and **compared back with what went in**. Anything that does not come back the same is flagged, not accepted.

**`Open` means two things** - a live quote and an undelivered order - and the cell does not say which. I split the 102 `Open` rows by whether the row has a PO or job number: **83 to "quote live", 19 to "order in progress"**. This moves the conversion rate, so it is a judgement call, and it is recorded in `cleaning_log`. Appendix A in `04_analysis_queries.sql` prints every status wording next to the state I mapped it to, so anyone can disagree with a specific line.

**The LD (liquidated damages) field** is spread over two columns and holds clauses, delivery months, payment terms, the word "Lost" and Excel timestamps. The cleaning step classifies what each cell actually is instead of trusting the column name.

## What I found

**LD is not recorded on most late orders.** 121 of 138 late orders (88%) have nothing in either LD column. Query 12 was meant to total the penalty exposure, but it cannot be totalled because the field is not kept.

**OTIF is 58.5%, and "on time" is the problem.**

| | Orders due | OTIF |
|---|---:|---:|
| Pressure Vessel | 154 | 59.7% |
| Grating | 79 | 59.5% |
| Pultrusion | 121 | 56.2% |
| **All** | **354** | **58.5%** |

In full is **91.2%**, on time is **61.0%**. Quantity is mostly fine. Dates are not.

**How often vs how bad.** From my Green Belt training: a Pareto by count and a Pareto by impact can give different priorities, so Q5 prints both side by side.
- Most frequent: *customer hold on drawing approval* - 28 late orders, 24.1 days average.
- Worst per order: *dimensional rework after inspection* - only 4 orders, but 53.8 days each.
- Biggest total loss: *transport not arranged* - 728 days across 21 orders.

**Revenue depends on very few customers.**

| Line | Top customer | Top 1 share | Top 5 share | Customers with revenue |
|---|---|---:|---:|---:|
| Pultrusion | C0013 | 89.3% | 100.0% | 4 |
| Grating | C0020 | 80.7% | 96.7% | 19 |
| Pressure Vessel | C0001 | 65.4% | 98.3% | 8 |

On grating, the top-5 share is pushed up by a few very large orders landing on big accounts. With only 144 grating rows that does not average out, so the direction is right but the size is overstated. Pultrusion's 100% is simply four customers.

**Old receivables.** ₹56.0 m is outstanding, and **78% of it is more than 90 days overdue** (54 invoices, 12 customers). That is roughly ₹44 m of working capital sitting with customers for over three months, and it is mostly the same few accounts that make up the revenue. Query 7 names them.

**Bigger vessels take longer, but only in bands.**

| Size band | Orders | Mean promised | Mean actual | Factor |
|---|---:|---:|---:|---:|
| Small (1400-1800) | 73 | 44 d | 45 d | 0.73 |
| Medium (2000-2400) | 51 | 60 d | 50 d | 1.00 |
| Large (2600-3000) | 48 | 114 d | 85 d | 1.90 |

Per single diameter there are only about 25 orders, and the spread is wide (the 90th percentile is 4.5 times the median), so the pattern disappears. That is why I grouped sizes into bands. Query 4 prints both tables.

## What I would do with this

1. Record the LD clause on every order, so penalty exposure can actually be measured.
2. Work on "on time", not "in full": book transport earlier (biggest total delay) and chase drawing approvals (most frequent delay).
3. Follow up the overdue invoices with the few big accounts first, since that is where most of the cash is.

## Running it

Needs **SQLite 3.25 or later** for the window functions (`ROW_NUMBER`, `RANK`, `LAG`, `NTILE`, running `SUM OVER`). macOS already has it; `sqlite3 --version` will tell you.

```bash
sqlite3 o2c.db < 01_schema.sql
python3 02_generate_data.py
sqlite3 o2c.db < 03_cleaning.sql
sqlite3 o2c.db < 04_analysis_queries.sql
sqlite3 o2c.db < 05_validation_checks.sql
```

`02_generate_data.py` only needs the Python standard library, and the seed is fixed at 42, so the database comes out the same every time.

If `sqlite3` is not installed, `run_sql.py` does the same through Python:

```bash
python3 run_sql.py 04_analysis_queries.sql
```

Each query has a comment on top with the business question, the tables it uses and the SQL features it uses.

## Files

| File | What it is |
|---|---|
| `01_schema.sql` | 12 tables. `raw_quote_register` is all TEXT on purpose |
| `02_generate_data.py` | Builds the tables and loads the database |
| `raw_register.py` | Builds the messy raw register; used by the above |
| `03_cleaning.sql` | Two views, and every cleaning decision written to `cleaning_log` |
| `04_analysis_queries.sql` | The 12 analysis queries |
| `05_validation_checks.sql` | 22 checks, one row each |
| `run_sql.py` | Runs any of the .sql files without the sqlite3 command line |
| `data_privacy_check.py` | Checks every table and file for names, emails, phone numbers, GSTIN and PAN; fails on any finding |
| `o2c.db` | The built database, ready to query |
| `model_parameters.json` | The parameter file the generator reads (shares, lead times, value ranges) |
| `data/raw_quote_register.csv` | The raw table as CSV |
| `data/query_results.txt` | Output of all 12 queries |
| `data/validation_results.txt` | Output of the validation checks |
| `data/generation_log.json` | Which rows carry which planted data error |

## The data model

```
customers ──┬── quotations ──── quotation_lines ──┐
            │        │                            ├── items
            ├── orders ──────── order_lines ──────┘
            │     │  └── quote_id can be empty (59.4% are)
            │     │
            │     └── dispatches ──── invoices ──── payments
            │                              │
            └──────────────────────────────┘

payment_terms ──── orders          (credit days set every due date)
raw_quote_register                 (standalone, all TEXT, never changed)
cleaning_log                       (one row per cleaning decision)
```

**OTIF:** an order is on time if every line is fully dispatched on or before the promised date (0 grace days, can be changed in `v_otif`), and in full if dispatched quantity is at least the ordered quantity on every line. Cancelled orders are left out, and so are orders whose promised date has not come yet - they are open orders, not failures.

## Validation

**22 checks: 20 PASS, 2 EXPECTED, 0 FAIL.** `PRAGMA foreign_key_check` returns no violations.

```bash
python3 run_sql.py 05_validation_checks.sql --checks
```

It prints one line per check and stops with an error if anything fails. EXPECTED means the check found exactly the data problem it was built to catch. If a run had no EXPECTED results, it would mean the mess had been cleaned away somewhere without being logged.

## Assumptions

- **Dispatch:** about 70% of orders are set up to ship on time and 92% in full.
- **Payment:** each customer has one payment habit and every invoice follows it, so query 7 shows habits and not noise. Two rules stop very old debt piling up just because of how the data is generated: invoices more than eight months past due are mostly moved to "paid late", and part payments more than six months past due are usually closed.
- **Size:** 625 register rows (204 vessel, 277 pultrusion, 144 grating); window 1 Apr 2024 to 31 Aug 2026; about 4% cancelled.
- **Money:** USD-INR 83-90; GST 18%, also on deemed exports, because under Indian GST the supplier charges it and the buyer claims it back.

## What this cannot tell you

- **Why anything is late.** There is a delay reason on each dispatch, but no supplier, material or shop-floor data behind it.
- **Anything about cost or margin.** The register only has a selling value.
- **Which record is right** where the register and the customer master disagree on market. 15 rows are flagged, not fixed.
- **Progress inside manufacturing.** Left out on purpose - this is the commercial journey, quote to cash.
- **A reliable lead time per size.** About 25 orders per diameter is not enough.
- **A broad customer Pareto.** Only 4 or 5 customers per line carry meaningful revenue.
