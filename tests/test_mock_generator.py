"""Tests for the mock image generator (plan task 9)."""

from genclaw.generators.mock import MockImageGenerator


def test_mock_creates_final_image(tmp_path):
    sketch = tmp_path / "sketch.png"
    sketch.write_bytes(b"\x89PNG\r\n\x1a\n fake png bytes")
    final = tmp_path / "final.png"

    result = MockImageGenerator().generate("three red circles", sketch, final)

    assert result.final_path == final
    assert final.exists()
    assert final.read_bytes() == sketch.read_bytes()


def test_metadata_records_provider_and_sketch(tmp_path):
    sketch = tmp_path / "sketch.png"
    sketch.write_bytes(b"x")
    final = tmp_path / "final.png"

    result = MockImageGenerator().generate("p", sketch, final, constraints={"seed": 1})

    assert result.provider == "mock"
    assert result.sketch_path == sketch
    assert result.metadata["constraints"] == {"seed": 1}
    assert "no photorealistic" in result.metadata["note"]
    assert result.metadata["sketch_existed"] is True


def test_missing_sketch_leaves_explicit_placeholder(tmp_path):
    sketch = tmp_path / "absent.png"
    final = tmp_path / "final.png"

    result = MockImageGenerator().generate("p", sketch, final)

    assert final.exists()
    assert result.metadata["sketch_existed"] is False
