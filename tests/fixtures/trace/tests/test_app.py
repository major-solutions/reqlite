import pytest

from app import calibrate, clamp, convert, debug_dump, fmt, gain, unit_factor, validate
from helpers import approx


# reqlite:begin SC-001 test
def test_convert_scales_and_clamps():
    assert convert(2.0, 3.0) == 6.0
    assert convert(5.0, 3.0) == 10.0
# reqlite:end SC-001


# reqlite:begin SC-002 test
def test_validate_accepts_numbers():
    assert validate(1.5)
# reqlite:end SC-002


# reqlite:begin SC-005 test
def test_calibration_forgets_to_calibrate():
    assert convert(1.0, 1.0) == 1.0
# reqlite:end SC-005


# reqlite:begin SC-009 test
def test_gain_rejects_negative():
    with pytest.raises(ValueError):
        gain(1.0, -1.0)
# reqlite:end SC-009


# reqlite:begin SC-010 test
def test_gain_scales():
    assert gain(2.0, 2.0) == 4.0
# reqlite:end SC-010


# reqlite:begin TC-001
def test_scaling_end_to_end():
    assert convert(1.0, unit_factor("V")) == 1.0
# reqlite:end TC-001


# reqlite:begin TC-002
def test_formatting():
    assert fmt(1.0) == "1.000"
# reqlite:end TC-002


# reqlite:begin TC-003
def test_validation_rejects_text():
    with pytest.raises(TypeError):
        validate("x")
# reqlite:end TC-003


# reqlite:begin TC-004
def test_unit_table():
    assert approx(unit_factor("mV"), 1e-3)
# reqlite:end TC-004


# reqlite:begin TC-005
def test_calibration():
    assert calibrate(5.0, 1.0) == 4.0
# reqlite:end TC-005


# reqlite:begin TC-006
def test_limits():
    assert clamp(50.0) == 10.0
    assert gain(1.0, 2.0) == 2.0
# reqlite:end TC-006


# reqlite:begin TC-007
def test_validation_dump():
    assert debug_dump(1) == "1"
# reqlite:end TC-007


def test_untraced():
    assert debug_dump(2) == "2"
