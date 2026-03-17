"""Tests for yesc subdirectory handling in standard packaging mode."""

import argparse
import importlib
import os
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
        "ioidtype": "",
        "ioidvalue": "",
        "soidtype": "",
        "soidvalue": "",
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


def _parse_xip(output_dir):
    """Find and parse the metadata.xml from the SIP output."""
    # SIP is at output_dir/{UUID}/metadata.xml
    sip_dirs = [d for d in Path(output_dir).iterdir() if d.is_dir()]
    assert len(sip_dirs) == 1, f"Expected 1 SIP dir, found {len(sip_dirs)}"
    xip_path = sip_dirs[0] / "metadata.xml"
    assert xip_path.exists(), f"metadata.xml not found in {sip_dirs[0]}"
    return ET.parse(str(xip_path))


class TestSubdirectoryPackaging:
    """Test that yesc packages files inside subdirectories."""

    def test_subdir_creates_sub_so(self, tmp_path):
        """Item with processed/ subfolder → XIP has sub-SO for 'processed'."""
        # Create input: item folder with processed/ subfolder containing files
        input_dir = tmp_path / "input" / "item1"
        proc_dir = input_dir / "processed"
        proc_dir.mkdir(parents=True)
        (proc_dir / "file1.tif").write_bytes(b"\x00" * 100)
        (proc_dir / "file2.tif").write_bytes(b"\x00" * 200)

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        args = _make_args(input_dir, output_dir)
        yesc_main(args)

        # Parse XIP and check for StructuralObject elements
        tree = _parse_xip(output_dir)
        root = tree.getroot()
        ns = "http://preservica.com/XIP/v6.2"
        sos = root.findall(f"{{{ns}}}StructuralObject")
        ios = root.findall(f"{{{ns}}}InformationObject")

        # Should have: 1 parent SO + 1 sub-SO for "processed" = 2 SOs
        assert len(sos) >= 2, f"Expected >= 2 SOs (parent + sub), got {len(sos)}"
        # Should have 2 IOs (one per file)
        assert len(ios) == 2, f"Expected 2 IOs, got {len(ios)}"

    def test_flat_files_unchanged(self, tmp_path):
        """Item with root-level files → packages correctly (no regression)."""
        input_dir = tmp_path / "input" / "item1"
        input_dir.mkdir(parents=True)
        (input_dir / "file1.tif").write_bytes(b"\x00" * 100)
        (input_dir / "file2.tif").write_bytes(b"\x00" * 200)

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        args = _make_args(input_dir, output_dir)
        yesc_main(args)

        tree = _parse_xip(output_dir)
        root = tree.getroot()
        ns = "http://preservica.com/XIP/v6.2"
        sos = root.findall(f"{{{ns}}}StructuralObject")
        ios = root.findall(f"{{{ns}}}InformationObject")

        # Flat: 1 parent SO, 2 IOs
        assert len(sos) == 1, f"Expected 1 SO, got {len(sos)}"
        assert len(ios) == 2, f"Expected 2 IOs, got {len(ios)}"

    def test_storageconfig_embeds_per_subfolder(self, tmp_path):
        """Multi-subfolder item + storageconfig → correct storage metadata per subfolder."""
        # Create input with two subfolders
        input_dir = tmp_path / "input" / "item1"
        proc_dir = input_dir / "processed"
        pres_dir = input_dir / "preservation"
        proc_dir.mkdir(parents=True)
        pres_dir.mkdir()
        (proc_dir / "file1.tif").write_bytes(b"\x00" * 100)
        (pres_dir / "file2.tif").write_bytes(b"\x00" * 200)

        # Create storage metadata XMLs (minimal valid format)
        storage_dir = tmp_path / "storage"
        storage_dir.mkdir()
        active_xml = storage_dir / "active.xml"
        active_xml.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<pstr xmlns="http://edu.yale/library/metadata/preservationStorage">'
            '<StoragePolicy>brbl_active_archive</StoragePolicy></pstr>'
        )
        glacier_xml = storage_dir / "glacier.xml"
        glacier_xml.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<pstr xmlns="http://edu.yale/library/metadata/preservationStorage">'
            '<StoragePolicy>brbl_archive_glacier</StoragePolicy></pstr>'
        )

        # Create storageconfig XML mapping subfolders to storage XMLs
        content_path = str(input_dir) + os.sep
        storageconfig_xml = storage_dir / "storageconfig.xml"
        storageconfig_xml.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<StorageConfig xmlns="http://edu.yale/library/metadata/storageconfig/v1">'
            f'<FolderConfig><FolderPrefix>processed</FolderPrefix>'
            f'<StorageKeyword>{active_xml}</StorageKeyword></FolderConfig>'
            f'<FolderConfig><FolderPrefix>preservation</FolderPrefix>'
            f'<StorageKeyword>{glacier_xml}</StorageKeyword></FolderConfig>'
            '</StorageConfig>'
        )

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        args = _make_args(input_dir, output_dir,
                          storageconfig=str(storageconfig_xml))
        yesc_main(args)

        # Parse XIP and check for Metadata elements (storage embedding)
        tree = _parse_xip(output_dir)
        root = tree.getroot()
        ns = "http://preservica.com/XIP/v6.2"
        metadata_elements = root.findall(f"{{{ns}}}Metadata")

        # Should have storage metadata embedded for each IO (2 files = 2 metadata)
        assert len(metadata_elements) >= 2, (
            f"Expected >= 2 Metadata elements (storage per IO), got {len(metadata_elements)}"
        )

        # Verify the storage policies are actually embedded
        xip_text = ET.tostring(root, encoding="unicode")
        assert "brbl_active_archive" in xip_text, "Missing active_archive storage policy"
        assert "brbl_archive_glacier" in xip_text, "Missing archive_glacier storage policy"
