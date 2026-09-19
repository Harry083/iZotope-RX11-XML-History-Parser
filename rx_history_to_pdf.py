#!/usr/bin/env python3
"""
rx_history_to_pdf.py

Converts an iZotope RX (RX10/RX11/etc.) "History" export XML file into a
clean, readable, presentable PDF report.

Usage:
    python3 rx_history_to_pdf.py INPUT.xml [OUTPUT.pdf] [options]

Options:
    --case-ref TEXT       Case / reference number to show on the cover page
    --exhibit TEXT        Exhibit reference to show on the cover page
    --examiner TEXT       Examiner / operator name to show on the cover page
    --notes TEXT          Free-text note to show on the cover page

The script is deliberately generic: it does not assume a fixed set of RX
operations or parameters. Any <Render> (or similar) step in the history,
with any <Key>/<Number> parameter pairs and/or <PolyRegion> selection data,
will be picked up and rendered automatically.
"""

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    KeepTogether,
)


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

POINT_RE = re.compile(r"\(\s*([\-\d\.]+)\s*,\s*([\-\d\.]+)\s*\)")


def fmt_time(seconds):
    """Format a duration in seconds as H:MM:SS.mmm (or M:SS.mmm if <1hr)."""
    if seconds is None:
        return None
    neg = seconds < 0
    seconds = abs(seconds)
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = seconds % 60
    if hrs:
        s = f"{hrs}:{mins:02d}:{secs:06.3f}"
    else:
        s = f"{mins}:{secs:06.3f}"
    return ("-" + s) if neg else s


def fmt_number(val):
    """Pretty-print a numeric string, trimming needless precision."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return val
    if f == int(f):
        return str(int(f))
    return f"{f:.4g}"


def parse_loop(loop_text, sample_rate):
    """Parse a PolyRegion <Loop> point list into a time/frequency bounding box."""
    pts = POINT_RE.findall(loop_text or "")
    if not pts:
        return None
    xs = [float(x) for x, _ in pts]
    ys = [float(y) for _, y in pts]
    box = {
        "frame_min": min(xs),
        "frame_max": max(xs),
        "freq_min": min(ys),
        "freq_max": max(ys),
    }
    if sample_rate:
        box["time_min"] = box["frame_min"] / sample_rate
        box["time_max"] = box["frame_max"] / sample_rate
    return box


def parse_region(region_el, sample_rate):
    """Parse a <PolyRegion> or <Region>-style element into a summary dict."""
    if region_el is None:
        return None
    loop_el = region_el.find("Loop")
    box = parse_loop(loop_el.text, sample_rate) if loop_el is not None else None
    feathering = region_el.findtext("Feathering")
    freq_feathering = region_el.findtext("FreqFeathering")
    full_band = None
    if box and sample_rate:
        # RX represents "whole spectrum selected" as freq_max ~= Nyquist
        nyquist = sample_rate / 2
        full_band = box["freq_max"] >= nyquist * 0.999 and box["freq_min"] <= 0.001
    return {
        "box": box,
        "feathering": feathering,
        "freq_feathering": freq_feathering,
        "full_band": full_band,
    }


def parse_step_element(step_el, sample_rate):
    """Parse one <Render> (or sibling) element under <History> generically."""
    step = {
        "kind": step_el.tag,  # e.g. "Render"
        "description": None,
        "operation_name": None,
        "timestamp": None,
        "undo_style": None,
        "parameters": [],  # list of (key, value)
        "region": None,
    }

    pending_key = None
    for child in step_el:
        tag = child.tag
        text = (child.text or "").strip()
        if tag == "Description":
            step["description"] = text
        elif tag == "OperationName":
            step["operation_name"] = text
        elif tag == "TimeStamp":
            step["timestamp"] = text
        elif tag == "UndoStyle":
            step["undo_style"] = text
        elif tag == "Key":
            pending_key = text
        elif tag in ("Number", "String", "Bool"):
            if pending_key is not None:
                step["parameters"].append((pending_key, text))
                pending_key = None
        elif tag in ("PolyRegion", "Region", "Selection"):
            step["region"] = parse_region(child, sample_rate)
        # Anything else (unknown future RX tags) is silently skipped so the
        # script keeps working on newer RX versions without crashing.

    return step


def parse_rx_history(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    data = {
        "product": root.attrib.get("product"),
        "generated_on": root.attrib.get("generated-on"),
        "format": root.attrib.get("format"),
        "source_files": [],
        "clip": {},
        "steps": [],
    }

    # Source file(s) - the tag name varies slightly between RX versions.
    for storage_tag in ("ClipStorageSingleFile", "ClipStorage", "ClipStorageMultiFile"):
        storage_el = root.find(storage_tag)
        if storage_el is not None:
            for f in storage_el.findall("File"):
                if f.text:
                    data["source_files"].append(f.text.strip())

    # Original clip info
    clip_el = root.find("OriginalClipInfo")
    sample_rate = None
    if clip_el is not None:
        for tag in ("ChannelCount", "BitsPerSample", "SamplingRate", "SampleFrameCount"):
            val = clip_el.findtext(tag)
            if val is not None:
                data["clip"][tag] = val.strip()
        data["clip"]["FloatingPoint"] = clip_el.find("FloatingPointSamples") is not None
        if "SamplingRate" in data["clip"]:
            try:
                sample_rate = float(data["clip"]["SamplingRate"])
            except ValueError:
                sample_rate = None

    if sample_rate and "SampleFrameCount" in data["clip"]:
        try:
            frames = float(data["clip"]["SampleFrameCount"])
            data["clip"]["Duration"] = frames / sample_rate
        except ValueError:
            pass

    data["clip"]["_sample_rate"] = sample_rate

    # History steps
    history_el = root.find("History")
    if history_el is not None:
        for step_el in history_el:
            data["steps"].append(parse_step_element(step_el, sample_rate))

    return data


# --------------------------------------------------------------------------
# PDF rendering
# --------------------------------------------------------------------------

BRAND_DARK = colors.HexColor("#1f2733")
BRAND_ACCENT = colors.HexColor("#2f6f8f")
ROW_ALT = colors.HexColor("#f2f5f7")
BORDER = colors.HexColor("#c9d2d8")


def build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle", parent=styles["Title"],
        fontSize=20, textColor=BRAND_DARK, spaceAfter=2,
    ))
    styles.add(ParagraphStyle(
        name="ReportSubtitle", parent=styles["Normal"],
        fontSize=11, textColor=colors.HexColor("#5a6875"), spaceAfter=14,
    ))
    styles.add(ParagraphStyle(
        name="SectionHeading", parent=styles["Heading2"],
        fontSize=13, textColor=BRAND_DARK, spaceBefore=16, spaceAfter=8,
        borderPadding=0,
    ))
    styles.add(ParagraphStyle(
        name="StepTitle", parent=styles["Normal"],
        fontSize=12, textColor=colors.white, fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        name="StepMeta", parent=styles["Normal"],
        fontSize=8.5, textColor=colors.white,
    ))
    styles.add(ParagraphStyle(
        name="Body", parent=styles["Normal"],
        fontSize=9.5, leading=13, alignment=TA_LEFT,
    ))
    styles.add(ParagraphStyle(
        name="MetaLabel", parent=styles["Normal"],
        fontSize=9, textColor=colors.HexColor("#5a6875"),
    ))
    styles.add(ParagraphStyle(
        name="MetaValue", parent=styles["Normal"],
        fontSize=9.5, textColor=BRAND_DARK,
    ))
    styles.add(ParagraphStyle(
        name="Footer", parent=styles["Normal"],
        fontSize=7.5, textColor=colors.HexColor("#8b97a1"),
    ))
    return styles


def meta_table(rows, styles, col_widths=(42 * mm, 130 * mm)):
    """A simple two-column label/value table used for metadata blocks."""
    data = [
        [Paragraph(f"<b>{label}</b>", styles["MetaLabel"]), Paragraph(str(value), styles["MetaValue"])]
        for label, value in rows if value not in (None, "", [])
    ]
    if not data:
        return None
    t = Table(data, colWidths=col_widths, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def build_cover_flowables(history, source_xml_name, case_info, styles):
    flow = []
    flow.append(Paragraph("Audio Processing History Report", styles["ReportTitle"]))
    flow.append(Paragraph("Generated from an iZotope RX history export", styles["ReportSubtitle"]))
    flow.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=12))

    case_rows = [
        ("Case reference", case_info.get("case_ref")),
        ("Exhibit reference", case_info.get("exhibit")),
        ("Examiner", case_info.get("examiner")),
        ("Report generated", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Notes", case_info.get("notes")),
    ]
    t = meta_table(case_rows, styles)
    if t:
        flow.append(t)
        flow.append(Spacer(1, 10))

    flow.append(Paragraph("Source", styles["SectionHeading"]))
    src_rows = [
        ("RX product / version", history.get("product")),
        ("History exported", history.get("generated_on")),
        ("History file", source_xml_name),
    ]
    for f in history.get("source_files", []):
        src_rows.append(("Audio file", f))
    t = meta_table(src_rows, styles)
    if t:
        flow.append(t)

    clip = history.get("clip", {})
    if clip:
        flow.append(Spacer(1, 10))
        flow.append(Paragraph("Audio properties", styles["SectionHeading"]))
        clip_rows = []
        if "ChannelCount" in clip:
            ch = clip["ChannelCount"]
            label = {"1": "Mono", "2": "Stereo"}.get(ch, f"{ch} channels")
            clip_rows.append(("Channels", label))
        if "BitsPerSample" in clip:
            bits = clip["BitsPerSample"]
            kind = "float" if clip.get("FloatingPoint") else "integer"
            clip_rows.append(("Bit depth", f"{bits}-bit {kind}"))
        if clip.get("_sample_rate"):
            clip_rows.append(("Sample rate", f"{fmt_number(clip['_sample_rate'])} Hz"))
        if "SampleFrameCount" in clip:
            clip_rows.append(("Sample frames", fmt_number(clip["SampleFrameCount"])))
        if "Duration" in clip:
            clip_rows.append(("Duration", fmt_time(clip["Duration"])))
        t = meta_table(clip_rows, styles)
        if t:
            flow.append(t)

    n_steps = len(history.get("steps", []))
    flow.append(Spacer(1, 10))
    flow.append(Paragraph(
        f"This report documents <b>{n_steps}</b> processing step"
        f"{'s' if n_steps != 1 else ''} applied to the audio, in the order they "
        f"were carried out, as recorded in the RX history file.",
        styles["Body"],
    ))
    return flow


def step_flowable(index, step, styles, page_width):
    """Render one processing step as a self-contained block (header + body)."""
    name = step.get("operation_name") or step.get("description") or step.get("kind")
    desc = step.get("description")
    header_bits = f"Step {index}: {name}"

    # Header bar (dark background, white text) implemented as a 1x2 table.
    header_data = [[
        Paragraph(header_bits, styles["StepTitle"]),
        Paragraph(step.get("timestamp") or "", styles["StepMeta"]),
    ]]
    header = Table(header_data, colWidths=[page_width - 40 * mm, 40 * mm])
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_DARK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 8),
        ("RIGHTPADDING", (-1, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))

    body_rows = []
    if desc and desc != name:
        body_rows.append(("Description", desc))

    region = step.get("region")
    if region and region.get("box"):
        box = region["box"]
        if "time_min" in box:
            time_range = f"{fmt_time(box['time_min'])} &ndash; {fmt_time(box['time_max'])}"
            body_rows.append(("Selected time range", time_range))
        if region.get("full_band"):
            body_rows.append(("Frequency range", "Full spectrum"))
        elif "freq_min" in box:
            freq_range = f"{fmt_number(box['freq_min'])} &ndash; {fmt_number(box['freq_max'])} Hz"
            body_rows.append(("Frequency range", freq_range))
        if region.get("feathering") not in (None, "0"):
            body_rows.append(("Feathering", f"{region['feathering']} px"))

    params = step.get("parameters") or []
    body_flow = []
    if body_rows:
        body_flow.append(meta_table(body_rows, styles, col_widths=(38 * mm, page_width - 38 * mm - 16 * mm)))

    if params:
        body_flow.append(Spacer(1, 4))
        body_flow.append(Paragraph("<b>Parameters</b>", styles["MetaLabel"]))
        param_data = [
            [Paragraph(k, styles["MetaValue"]), Paragraph(fmt_number(v), styles["MetaValue"])]
            for k, v in params
        ]
        pt = Table(param_data, colWidths=[(page_width - 16 * mm) * 0.55, (page_width - 16 * mm) * 0.45])
        pt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), ROW_ALT),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, ROW_ALT]),
            ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        body_flow.append(pt)

    if not body_flow:
        body_flow.append(Paragraph("<i>No additional parameters recorded.</i>", styles["Body"]))

    wrapper = Table([[body_flow]], colWidths=[page_width])
    wrapper.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.75, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))

    return KeepTogether([header, wrapper, Spacer(1, 10)])


def footer(canvas_obj, doc):
    canvas_obj.saveState()
    canvas_obj.setFont("Helvetica", 7.5)
    canvas_obj.setFillColor(colors.HexColor("#8b97a1"))
    canvas_obj.drawString(20 * mm, 12 * mm, "Generated from iZotope RX history export")
    canvas_obj.drawRightString(
        doc.pagesize[0] - 20 * mm, 12 * mm, f"Page {doc.page}"
    )
    canvas_obj.restoreState()


def build_pdf(history, source_xml_name, out_path, case_info):
    styles = build_styles()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm,
        title="Audio Processing History Report",
    )
    page_width = doc.width

    story = []
    story.extend(build_cover_flowables(history, source_xml_name, case_info, styles))
    story.append(Spacer(1, 16))
    story.append(Paragraph("Processing steps", styles["SectionHeading"]))

    steps = history.get("steps", [])
    if not steps:
        story.append(Paragraph("No processing steps were found in this history file.", styles["Body"]))
    else:
        for i, step in enumerate(steps, start=1):
            story.append(step_flowable(i, step, styles, page_width))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Convert an iZotope RX history XML export into a readable PDF report.")
    parser.add_argument("input", help="Path to the RX history .xml file")
    parser.add_argument("output", nargs="?", help="Path to write the PDF (defaults to input name with .pdf)")
    parser.add_argument("--case-ref", dest="case_ref", default=None)
    parser.add_argument("--exhibit", dest="exhibit", default=None)
    parser.add_argument("--examiner", dest="examiner", default=None)
    parser.add_argument("--notes", dest="notes", default=None)
    args = parser.parse_args(argv)

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"Input file not found: {in_path}", file=sys.stderr)
        return 1

    out_path = Path(args.output) if args.output else in_path.with_suffix(".pdf")

    history = parse_rx_history(in_path)
    case_info = {
        "case_ref": args.case_ref,
        "exhibit": args.exhibit,
        "examiner": args.examiner,
        "notes": args.notes,
    }
    build_pdf(history, in_path.name, out_path, case_info)
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
