# iZotope-RX11-XML-History-Parser

Convert an iZotope RX (RX10/RX11/etc.) **History** export XML file into a clean,
readable, presentable PDF report — useful for case files, exhibit bundles, and
handover documentation where you need a human-readable record of every
processing step applied to an audio file.

The parser is deliberately generic: it doesn't assume a fixed set of RX
operations or parameters. Any `<Render>` (or similar) step in the history,
with any `<Key>`/`<Number>` parameter pairs and/or `<PolyRegion>` selection
data, is picked up and rendered automatically — so the script should keep
working as RX adds new tools, without code changes.

## What it produces

A multi-page A4 PDF with:

- **Cover page** — case reference, exhibit reference, examiner, notes,
  report generation timestamp, source audio file(s), RX product/version, and
  audio properties (channels, bit depth, sample rate, duration).
- **Processing steps** — one block per history entry, in order, each showing
  the operation name, timestamp, description, selected time/frequency range
  (where recorded), feathering, and the full parameter table for that step.

## Installation

```bash
git clone https://github.com/<Harry083>/iZotope-RX11-XML-History-Parser.git
cd iZotope-RX11-XML-History-Parser
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Requires Python 3.9+ and [ReportLab](https://pypi.org/project/reportlab/).

Optionally install it as a command-line tool:

```bash
pip install .
```

which puts an `iZotope-RX11-XML-History-Parser` command on your `PATH`.

## Usage

```bash
python3 rx_history_to_pdf.py INPUT.xml [OUTPUT.pdf] [options]
```

If `OUTPUT.pdf` is omitted, the PDF is written alongside the input file with
the same name and a `.pdf` extension.

### Options

| Option | Description |
|---|---|
| `--case-ref TEXT` | Case / reference number to show on the cover page |
| `--exhibit TEXT` | Exhibit reference to show on the cover page |
| `--examiner TEXT` | Examiner / operator name to show on the cover page |
| `--notes TEXT` | Free-text note to show on the cover page |

### Example

```bash
python3 rx_history_to_pdf.py "Exhibit_04_History.xml" report.pdf \
    --case-ref "CR/2026/00123" \
    --exhibit "EX/04" \
    --examiner "H. Smallwood" \
    --notes "History export taken directly from RX11 project prior to any further processing."
```

## Where does the History XML come from?

In RX, open the **History** panel for a file, then use its export/save
option to write the panel out as XML. The exported file is what this script
expects as `INPUT.xml`.

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Tests live in `tests/` and cover the parsing helpers (`fmt_time`,
`fmt_number`, `parse_loop`, `parse_region`) and a full parse of a small
synthetic history file in `tests/fixtures/sample_history.xml`.

## Notes / limitations

- The script only reads the History XML export; it does not open or touch
  the original audio file.
- Field names and structure are based on the RX History XML schema as
  observed in RX10/RX11 exports. Unknown/future tags under a step are
  silently skipped rather than causing a crash, but genuinely new top-level
  sections (outside `<History>`) may not be picked up — please open an issue
  with a redacted sample if you hit one.
- This tool does not verify or attest to the authenticity of the XML it is
  given; treat the produced PDF as a formatting convenience, not evidence in
  itself.

