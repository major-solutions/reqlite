"""A toy instrument library: one planted case per trace-compare finding."""

# reqlite:begin SC-006
UNITS = {"mV": 1e-3, "V": 1.0}


def unit_factor(unit):
    return UNITS[unit]
# reqlite:end SC-006


# reqlite:begin SC-004
def clamp(x, lo=-10.0, hi=10.0):
    return max(lo, min(hi, x))
# reqlite:end SC-004


# reqlite:begin SC-001
def convert(value, factor):
    return clamp(value * factor)
# reqlite:end SC-001


# reqlite:begin SC-003
def fmt(x):
    return f"{x:.3f}"
# reqlite:end SC-003


# reqlite:begin SC-008
def legacy_export(values):
    return ";".join(str(v) for v in values)
# reqlite:end SC-008


# reqlite:begin SC-002
def validate(x):
    if not isinstance(x, (int, float)):
        raise TypeError("not a number")
    legacy_export([x])
    return True
# reqlite:end SC-002


# reqlite:begin SC-005
def calibrate(x, offset):
    return x - offset
# reqlite:end SC-005


# reqlite:begin SC-007
def drift(x, t):
    return x * (1 + 1e-6 * t)
# reqlite:end SC-007


def gain(x, k):
    # reqlite:begin SC-009
    if k < 0:
        raise ValueError("negative gain")
    # reqlite:end SC-009
    # reqlite:begin SC-010
    return clamp(x * k)
    # reqlite:end SC-010


def debug_dump(x):
    return repr(x)
