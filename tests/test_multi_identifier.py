"""Tests for multi-identifier support in yesc (SO and IO levels)."""

import importlib
import sys
from pathlib import Path
from lxml import etree as et

# Import yesc.py directly (avoid conflict with installed single-file module)
for _key in list(sys.modules):
    if _key == "yesc" or _key.startswith("yesc."):
        del sys.modules[_key]
_script_path = Path(__file__).resolve().parent.parent / "yesc.py"
_spec = importlib.util.spec_from_file_location("yesc_module", _script_path)
yesc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(yesc)


class TestGenId:
    """Test gen_id() directly."""

    def test_single_element(self):
        """gen_id returns an Identifier element with Type, Value, Entity."""
        elem = yesc.gen_id("mmsid", "998123", "test-uuid")
        assert elem.tag == "Identifier"
        assert elem.find("Type").text == "mmsid"
        assert elem.find("Value").text == "998123"
        assert elem.find("Entity").text == "test-uuid"


class TestMultiSOIdentifiers:
    """Test multiple SO identifiers in XIP output."""

    def _make_args(self, soidtype=None, soidvalue=None, **overrides):
        """Build minimal args for create_xip with identifier support."""
        import argparse
        import tempfile
        import os

        defaults = {
            "input": "",
            "output": "",
            "sotitle": 0,
            "parent": "None",
            "securitytag": "BRBL_OPEN",
            "assetonly": False,
            "singleasset": False,
            "iotitle": 0,
            "export": False,
            "aspace": None,
            "sodescription": "Test",
            "iodescription": None,
            "sometadata": None,
            "iometadata": None,
            "ioidtype": None,
            "ioidvalue": None,
            "soidtype": soidtype,
            "soidvalue": soidvalue,
            "representations": False,
            "sipconfig": None,
            "storage": None,
            "storageconfig": None,
            "md5": False,
            "sha1": False,
            "sha256": False,
            "sha512": True,
            "excludedFileNames": "",
            "prefix": "",
        }
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_single_so_pair(self, tmp_path):
        """Single SO identifier pair → one Identifier element."""
        # Create minimal input
        item_dir = tmp_path / "item"
        proc = item_dir / "processed"
        proc.mkdir(parents=True)
        (proc / "file.txt").write_text("test")

        args = self._make_args(
            soidtype=["mmsid"], soidvalue=["998123"],
            input=str(item_dir), output=str(tmp_path / "out"),
            export=False,
        )
        (tmp_path / "out").mkdir()

        yesc.main(args)

        # Find the XIP file
        xip_files = list((tmp_path / "out").rglob("metadata.xml"))
        assert len(xip_files) == 1
        tree = et.parse(str(xip_files[0]))
        ns = {"x": "http://preservica.com/XIP/v6.2"}
        ids = tree.findall(".//x:Identifier", ns)
        # Should have at least 1 SO identifier
        so_ids = [i for i in ids if i.find("x:Type", ns).text == "mmsid"]
        assert len(so_ids) == 1
        assert so_ids[0].find("x:Value", ns).text == "998123"

    def test_three_so_pairs(self, tmp_path):
        """Three SO identifier pairs → three Identifier elements."""
        item_dir = tmp_path / "item"
        proc = item_dir / "processed"
        proc.mkdir(parents=True)
        (proc / "file.txt").write_text("test")

        args = self._make_args(
            soidtype=["mmsid", "holding", "barcode"],
            soidvalue=["998123", "228571", "390020"],
            input=str(item_dir), output=str(tmp_path / "out"),
            export=False,
        )
        (tmp_path / "out").mkdir()

        yesc.main(args)

        xip_files = list((tmp_path / "out").rglob("metadata.xml"))
        assert len(xip_files) == 1
        tree = et.parse(str(xip_files[0]))
        ns = {"x": "http://preservica.com/XIP/v6.2"}
        ids = tree.findall(".//x:Identifier", ns)
        type_texts = [i.find("x:Type", ns).text for i in ids]
        assert "mmsid" in type_texts
        assert "holding" in type_texts
        assert "barcode" in type_texts

    def test_none_no_identifiers(self, tmp_path):
        """None soidtype → no Identifier elements."""
        item_dir = tmp_path / "item"
        proc = item_dir / "processed"
        proc.mkdir(parents=True)
        (proc / "file.txt").write_text("test")

        args = self._make_args(
            soidtype=None, soidvalue=None,
            input=str(item_dir), output=str(tmp_path / "out"),
            export=False,
        )
        (tmp_path / "out").mkdir()

        yesc.main(args)

        xip_files = list((tmp_path / "out").rglob("metadata.xml"))
        assert len(xip_files) == 1
        tree = et.parse(str(xip_files[0]))
        ns = {"x": "http://preservica.com/XIP/v6.2"}
        ids = tree.findall(".//x:Identifier", ns)
        assert len(ids) == 0

    def test_so_length_mismatch(self, tmp_path):
        """Mismatched soidtype/soidvalue lengths → ValueError."""
        import pytest
        item_dir = tmp_path / "item"
        proc = item_dir / "processed"
        proc.mkdir(parents=True)
        (proc / "file.txt").write_text("test")

        args = self._make_args(
            soidtype=["mmsid", "barcode"], soidvalue=["998123"],
            input=str(item_dir), output=str(tmp_path / "out"),
            export=False,
        )
        (tmp_path / "out").mkdir()

        with pytest.raises(ValueError, match="same number of times"):
            yesc.main(args)
