import json

import pytest

from hil.pytest_plugin import artifact_dir_name

DUT = """
dut: demo
profile: standard-v1
signals:
  supply: PWR
  door_sensor: X1.1
  alarm_out: X2.1
  sensor_in3: AO.1
"""


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("HIL_STATION", raising=False)
    monkeypatch.delenv("HIL_DUT", raising=False)


def run(pytester, test_source, *extra):
    pytester.makefile(".yaml", dut=DUT)
    pytester.makepyfile(test_source)
    return pytester.runpytest(
        "--hil-station", "sim", "--hil-dut", "dut.yaml", "--hil-out", "out", *extra
    )


def test_loopback_passes_and_records_events(pytester):
    result = run(
        pytester,
        """
        def test_loop(dut):
            dut.supply.on()
            dut.door_sensor.set(True)
            dut.alarm_out.wait_for(True, timeout=0.5)
        """,
    )
    result.assert_outcomes(passed=1)
    nodeid = "test_loopback_passes_and_records_events.py::test_loop"
    events = pytester.path / "out" / artifact_dir_name(nodeid)
    actions = [
        json.loads(line).get("action")
        for line in (events / "events.jsonl").read_text().splitlines()
    ]
    assert "on" in actions
    assert "set" in actions
    assert "safe_state" in actions


def test_unwired_signal_skips(pytester):
    result = run(
        pytester,
        """
        def test_analog(dut):
            dut.sensor_in3
        """,
        "-rs",
    )
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(["*signal 'sensor_in3'*'AO.1' is not wired*"])


def test_unwired_signal_in_fixture_skips(pytester):
    result = run(
        pytester,
        """
        import pytest

        @pytest.fixture
        def analog(dut):
            return dut.sensor_in3

        def test_analog(analog):
            assert False
        """,
    )
    result.assert_outcomes(skipped=1)


def test_marker_skips_before_test_body(pytester):
    result = run(
        pytester,
        """
        import pytest

        @pytest.mark.hil_requires("sensor_in3")
        def test_analog(dut):
            assert False, "must not run"
        """,
    )
    result.assert_outcomes(skipped=1)


def test_marker_with_unknown_signal_errors(pytester):
    result = run(
        pytester,
        """
        import pytest

        @pytest.mark.hil_requires("nope")
        def test_x(dut):
            pass
        """,
    )
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*has no signal 'nope'*"])


def test_typo_in_signal_name_fails(pytester):
    result = run(
        pytester,
        """
        def test_x(dut):
            dut.door_sensr.set(True)
        """,
    )
    result.assert_outcomes(failed=1)


def test_safe_state_after_failed_test(pytester):
    result = run(
        pytester,
        """
        def test_1_fails_with_power_on(dut):
            dut.supply.on()
            assert False

        def test_2_power_is_off(dut, hil):
            assert not hil.devices["rel1"].states[0]
            assert not dut.supply.is_on
        """,
    )
    result.assert_outcomes(failed=1, passed=1)


def test_no_station_configured_is_an_error(pytester, monkeypatch):
    monkeypatch.setenv("HIL_STATION", "")
    pytester.makepyfile("def test_x(dut):\n    pass\n")
    result = pytester.runpytest()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*no HIL station configured*"])


def test_environment_variables(pytester, monkeypatch):
    pytester.makefile(".yaml", dut=DUT)
    pytester.makepyfile("def test_x(dut):\n    assert dut.name == 'demo'\n")
    monkeypatch.setenv("HIL_STATION", "sim")
    monkeypatch.setenv("HIL_DUT", "dut.yaml")
    pytester.runpytest().assert_outcomes(passed=1)


def test_config_error_stops_session(pytester):
    pytester.makefile(
        ".yaml",
        broken="name: b\nprofile: standard-v1\ndevices: {r: {driver: nope}}\nterminals: {}\n",
    )
    pytester.makepyfile("def test_x(hil):\n    pass\n")
    result = pytester.runpytest("--hil-station", "broken.yaml")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "unknown driver 'nope'" in result.stdout.str() + result.stderr.str()


def test_safe_state_failure_stops_session(pytester):
    result = run(
        pytester,
        """
        from hil.errors import DeviceError

        def test_1_breaks_relays(dut, hil):
            hil.devices["rel1"].fail_with = DeviceError("bus down")

        def test_2_must_not_run(dut):
            pass
        """,
        "-v",
    )
    output = result.stdout.str() + result.stderr.str()
    assert result.ret == 3
    assert "could not reach the safe state" in output
    assert "bus down" in output
    assert "test_2_must_not_run PASSED" not in output


def test_hil_fixture_without_dut(pytester):
    pytester.makepyfile(
        """
        def test_x(hil):
            hil.power.on("PWR")
            assert hil.devices["rel1"].states[0]
        """
    )
    pytester.runpytest("--hil-station", "sim").assert_outcomes(passed=1)


def test_unwired_signal_in_module_scoped_fixture_skips(pytester):
    result = run(
        pytester,
        """
        import pytest
        from hil.dut import Dut

        @pytest.fixture(scope="module")
        def analog(hil, hil_dut_config):
            return Dut(hil_dut_config, hil).sensor_in3

        def test_a(analog):
            pass

        def test_b(analog):
            pass
        """,
    )
    result.assert_outcomes(skipped=2)


def test_tests_using_only_hil_get_safe_state_and_artifacts(pytester):
    pytester.makepyfile(
        """
        def test_a(hil):
            hil.power.on("PWR")

        def test_b(hil):
            assert not hil.power["PWR"].is_on
        """
    )
    result = pytester.runpytest("--hil-station", "sim", "--hil-out", "out")
    result.assert_outcomes(passed=2)
    nodeid = "test_tests_using_only_hil_get_safe_state_and_artifacts.py::test_a"
    assert (pytester.path / "out" / artifact_dir_name(nodeid) / "events.jsonl").exists()


def test_artifact_dir_names_do_not_collide():
    assert artifact_dir_name("t.py::test[a/b]") != artifact_dir_name("t.py::test[a_b]")
    assert artifact_dir_name("t.py::test_x").startswith("t.py_test_x-")
    assert not artifact_dir_name("t.py::test_x.").endswith(".")
    long = "t.py::test[" + "x" * 300 + "]"
    assert len(artifact_dir_name(long)) <= 160
    assert artifact_dir_name(long) != artifact_dir_name(long + "y")
