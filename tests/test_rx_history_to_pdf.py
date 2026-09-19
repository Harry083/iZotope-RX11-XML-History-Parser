"""
Unit and integration tests for rx_history_to_pdf.py

Run with:
    pytest
"""

import sys
from pathlib import Path

import pytest

# Make the top-level script importable as a module without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rx_history_to_pdf as rxp  # noqa: E402


FIXTURE = Path(__file__).parent / "fixtures" / "sample_history.xml"


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------

def test_fmt_time_under_an_hour():
    assert rxp.fmt_time(65.5) == "1:05.500"


def test_fmt_time_over_an_hour():
    assert rxp.fmt_time(3725.25) == "1:02:05.250"


def test_fmt_time_negative():
    assert rxp.fmt_time(-1.5) == "-0:01.500"


def test_fmt_time_none():
    assert rxp.fmt_time(None) is None


def test_fmt_number_integer_valued_float():
    assert rxp.fmt_number("50.0") == "50"


def test_fmt_number_trims_precision():
    assert rxp.fmt_number("8.53219") == "8.532"


def test_fmt_number_non_numeric_passthrough():
    assert rxp.fmt_number("not-a-number") == "not-a-number"


# --------------------------------------------------------------------------
# Region / loop parsing
# --------------------------------------------------------------------------

def test_parse_loop_bounding_box():
    box = rxp.parse_loop("(0,0) (2400000,0) (2400000,24000) (0,24000)", sample_rate=48000)
    assert box["frame_min"] == 0
    assert box["frame_max"] == 2400000
    assert box["freq_min"] == 0
    assert box["freq_max"] == 24000
    assert box["time_min"] == 0
    assert box["time_max"] == 50.0


def test_parse_loop_empty_returns_none():
    assert rxp.parse_loop("", sample_rate=48000) is None
    assert rxp.parse_loop(None, sample_rate=48000) is None


# --------------------------------------------------------------------------
# Full history parse (integration)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def parsed():
    return rxp.parse_rx_history(FIXTURE)


def test_parses_top_level_metadata(parsed):
    assert parsed["product"] == "iZotope RX 11 Advanced"
    assert parsed["source_files"] == [
        r"C:\Cases\CR-2026-00123\Exhibit_04\original_audio.wav"
    ]


def test_parses_clip_info(parsed):
    clip = parsed["clip"]
    assert clip["ChannelCount"] == "2"
    assert clip["BitsPerSample"] == "24"
    assert clip["_sample_rate"] == 48000.0
    assert clip["Duration"] == pytest.approx(100.0)


def test_parses_all_steps_in_order(parsed):
    steps = parsed["steps"]
    assert len(steps) == 2
    assert steps[0]["operation_name"] == "De-hum"
    assert steps[1]["operation_name"] == "Spectral De-noise"


def test_step_parameters(parsed):
    dehum = parsed["steps"][0]
    assert ("Frequency", "50") in dehum["parameters"]
    assert ("Q", "12") in dehum["parameters"]


def test_step_region_bounding_box(parsed):
    denoise = parsed["steps"][1]
    region = denoise["region"]
    assert region is not None
    assert region["box"]["time_max"] == 50.0
    assert region["feathering"] == "4"


# --------------------------------------------------------------------------
# End-to-end PDF generation smoke test
# --------------------------------------------------------------------------

def test_build_pdf_writes_a_file(tmp_path):
    out_path = tmp_path / "report.pdf"
    history = rxp.parse_rx_history(FIXTURE)
    case_info = {
        "case_ref": "CR/2026/00123",
        "exhibit": "EX/04",
        "examiner": "Test Examiner",
        "notes": "Generated during automated tests.",
    }
    rxp.build_pdf(history, FIXTURE.name, out_path, case_info)

    assert out_path.exists()
    assert out_path.stat().st_size > 0
    with open(out_path, "rb") as f:
        assert f.read(5) == b"%PDF-"
