"""Tests for .protocol stats reflecting SIP content, not raw source-folder totals.

Bug: main() calls create_protocol() before create_xip(), and create_protocol()
runs data_stats() -- an unfiltered rglob -- so .protocol <files>/<size> (and the
sip_report dict built from the same values) describe the input directory rather
than what was packaged. Excluded files (Thumbs.db, .DS_Store, desktop.ini, ...)
are counted even though include_files() keeps them out of the SIP.
"""

import argparse
import importlib
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

# Import yesc.py directly (avoid conflict with installed single-file module)
for _key in list(sys.modules):
    if _key == "yesc" or _key.startswith("yesc."):
        del sys.modules[_key]
_script_path = Path(__file__).resolve().parent.parent / "yesc.py"
_spec = importlib.util.spec_from_file_location("yesc_module", _script_path)
_yesc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_yesc)
yesc_main = _yesc.main
data_stats = _yesc.data_stats

# The exclusion list used throughout: exact names only, so the tests behave the
# same on a yesc build without fnmatch support.
EXCLUSIONS = "Thumbs.db,.DS_Store,desktop.ini,.BridgeSort"


def _make_args(input_dir, output_dir, **overrides):
    """Build a minimal args namespace for yesc.main()."""
    defaults = {
        "input": str(input_dir),
        "output": str(output_dir),
        "securitytag": "open",
        "parent": None,
        "aspace": "",
        "prefix": "",
        "sotitle": "",
        "iotitle": "",
        "sodescription": "",
        "iodescription": "",
        "sometadata": "",
        "iometadata": "",
        "ioidtype": None,
        "ioidvalue": None,
        "soidtype": None,
        "soidvalue": None,
        "sipconfig": "",
        "excludedFileNames": "",
        "assetonly": "",
        "singleasset": "",
        "export": True,
        "representations": "",
        "md5": False,
        "sha1": False,
        "sha256": True,
        "sha512": False,
        "storage": "",
        "storageconfig": "",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _make_mixed_item(base_dir):
    """Build the sample-07 shape: item/processed/ with 3 content + 4 junk files.

    Mirrors research/samples/sample-07-protocol-exclusion/ exactly:
    3 files / 300 bytes of content, 7 files / 400 bytes on disk.
    """
    proc_dir = base_dir / "item_ao1234" / "processed"
    proc_dir.mkdir(parents=True)
    for name in ("img_0001.tif", "img_0002.tif", "img_0003.tif"):
        (proc_dir / name).write_bytes(b"\x00" * 100)
    for name in ("Thumbs.db", ".DS_Store", "desktop.ini", ".BridgeSort"):
        (proc_dir / name).write_bytes(b"\x00" * 25)
    return base_dir / "item_ao1234"


def _read_protocol(output_dir):
    """Parse the single .protocol file written into output_dir."""
    protocol_files = []
    for path in Path(output_dir).glob("*.protocol"):
        protocol_files.append(path)
    assert len(protocol_files) == 1, (
        f"Expected 1 .protocol file, found {len(protocol_files)}: {protocol_files}"
    )
    root = ET.parse(str(protocol_files[0])).getroot()
    ns = "http://www.tessella.com/xipcreateprotocol/v1"
    file_count = int(root.find(f"{{{ns}}}files").text)
    data_size = int(root.find(f"{{{ns}}}size").text)
    return file_count, data_size


def _count_sip_content(output_dir):
    """Count files and bytes actually copied into the SIP's content/ tree.

    Uses rglob because this build nests content under the source subfolder name
    ({uuid}/content/processed/img_0001.tif), so a non-recursive glob would find
    a directory and zero files.
    """
    sip_dirs = []
    for entry in Path(output_dir).iterdir():
        if entry.is_dir():
            sip_dirs.append(entry)
    assert len(sip_dirs) == 1, f"Expected 1 SIP dir, found {len(sip_dirs)}"

    content_root = sip_dirs[0] / "content"
    file_count = 0
    data_size = 0
    for path in content_root.rglob("*"):
        if path.is_file():
            file_count += 1
            data_size += path.stat().st_size
    return file_count, data_size


class TestDataStatsExclusions:
    """data_stats() must honour the exclusion list it is given."""

    def test_data_stats_excludes_listed_names(self, tmp_path):
        """THE BUG: junk files named in the exclusion list must not be counted."""
        item_dir = _make_mixed_item(tmp_path)

        file_count, data_size = data_stats(str(item_dir), EXCLUSIONS)

        assert file_count == 3, f"Expected 3 content files, got {file_count}"
        assert data_size == 300, f"Expected 300 content bytes, got {data_size}"

    def test_data_stats_counts_everything_when_no_exclusions(self, tmp_path):
        """No exclusion list means count everything -- unchanged for old callers."""
        item_dir = _make_mixed_item(tmp_path)

        # both the omitted-argument and explicit-None/empty forms
        assert data_stats(str(item_dir)) == (7, 400)
        assert data_stats(str(item_dir), None) == (7, 400)
        assert data_stats(str(item_dir), "") == (7, 400)

    def test_data_stats_recurses_nested_subfolders(self, tmp_path):
        """DSCA's two-level item/processed/ shape, plus a deeper level."""
        item_dir = tmp_path / "item_ao9999"
        proc_dir = item_dir / "processed"
        nested_dir = proc_dir / "nested"
        nested_dir.mkdir(parents=True)
        (item_dir / "root_file.tif").write_bytes(b"\x00" * 10)
        (proc_dir / "img_0001.tif").write_bytes(b"\x00" * 100)
        (proc_dir / "Thumbs.db").write_bytes(b"\x00" * 25)
        (nested_dir / "img_0002.tif").write_bytes(b"\x00" * 100)
        (nested_dir / "desktop.ini").write_bytes(b"\x00" * 25)

        file_count, data_size = data_stats(str(item_dir), EXCLUSIONS)

        # 3 kept files across 3 levels; the 2 junk files at 2 levels are dropped
        assert file_count == 3, f"Expected 3 files, got {file_count}"
        assert data_size == 210, f"Expected 210 bytes, got {data_size}"


class TestProtocolMatchesSip:
    """End-to-end: .protocol must describe the SIP, not the source folder."""

    def test_protocol_matches_sip_when_exclusions_fire(self, tmp_path):
        """Standard export mode: .protocol <files>/<size> == what landed in content/."""
        item_dir = _make_mixed_item(tmp_path / "input")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        args = _make_args(item_dir, output_dir, excludedFileNames=EXCLUSIONS)
        yesc_main(args)

        protocol_count, protocol_size = _read_protocol(output_dir)
        sip_count, sip_size = _count_sip_content(output_dir)

        # the SIP side is the packing path and is not what is under test --
        # assert it separately so a packing regression is distinguishable
        assert (sip_count, sip_size) == (3, 300), (
            f"SIP content should be 3 files / 300 bytes, got {sip_count} / {sip_size}"
        )
        assert (protocol_count, protocol_size) == (sip_count, sip_size), (
            f".protocol says {protocol_count} files / {protocol_size} bytes, "
            f"SIP holds {sip_count} files / {sip_size} bytes"
        )

    def test_main_tolerates_namespace_without_excludedfilenames(self, tmp_path):
        """A hand-built Namespace omitting excludedFileNames must not break create_protocol().

        yesc-bulk and other programmatic callers construct their Namespace by hand,
        so main() reads the field defensively rather than by attribute access. The
        packing paths read it directly and are out of scope for this fix, so main()
        may still fail later -- the guarantee under test is that the .protocol gets
        written with correct stats.
        """
        item_dir = tmp_path / "input" / "item_ao1234"
        item_dir.mkdir(parents=True)
        (item_dir / "img_0001.tif").write_bytes(b"\x00" * 100)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        args = _make_args(item_dir, output_dir)
        del args.excludedFileNames

        try:
            yesc_main(args)
        except AttributeError as err:
            # tolerated only if it came from a packing path, not from create_protocol
            assert "excludedFileNames" in str(err)

        assert _read_protocol(output_dir) == (1, 100)


class TestSipReportContract:
    """The dict returned to yesc-bulk and patron-packaging.py must not change shape."""

    def test_sip_report_keys_unchanged(self, tmp_path):
        """Keys and types stay as they are; only the values become correct."""
        item_dir = _make_mixed_item(tmp_path / "input")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        args = _make_args(item_dir, output_dir, excludedFileNames=EXCLUSIONS)
        report = yesc_main(args)

        assert set(report.keys()) == {"protocol_ref", "filecount", "size_bytes"}
        assert isinstance(report["protocol_ref"], str)
        assert isinstance(report["filecount"], int)
        assert isinstance(report["size_bytes"], int)
        assert report["filecount"] == 3
        assert report["size_bytes"] == 300
