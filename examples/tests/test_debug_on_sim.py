"""Debug probe examples on the built-in simulated station.

On a real station the image is the build output of the DUT firmware and the probe is
OpenOCD with an ST-Link.

    python -m pytest examples/tests --hil-station sim --hil-dut examples/dut.yaml
"""


def test_flash_and_reset(dut, hil, tmp_path):
    image = tmp_path / "firmware.bin"
    image.write_bytes(bytes(1024))
    assert dut.firmware.flash(image).ok
    dut.firmware.reset()
    actions = [call[1] for call in hil.devices["probe"].calls]
    assert actions[-2:] == ["flash", "reset"]


def test_interrupted_update(dut, tmp_path):
    image = tmp_path / "firmware.bin"
    image.write_bytes(bytes(1024))
    assert dut.firmware.flash_interrupted(image, after_s=0.01).interrupted
