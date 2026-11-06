"""Keep jointly installed TLS and manually qualified Kitten locks compatible."""
import ast
import itertools
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
MARKER_VALUES = {
    "sys_platform": {"linux", "darwin", "win32"},
    "platform_machine": {"x86_64", "AMD64", "aarch64", "arm64"},
    "platform_python_implementation": {"CPython", "PyPy"},
    "implementation_name": {"cpython", "pypy", "PyPy"},
}


def marker_applies(marker, environment):
    """Evaluate the equality-only platform markers used by the shared pins.

    Unknown marker syntax fails closed so a changed resolver expression needs
    explicit review instead of silently dropping a compatibility check.
    """
    if not marker:
        return True

    def visit(node):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            values = [visit(value) for value in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if (isinstance(node, ast.Compare) and len(node.ops) == 1
                and isinstance(node.ops[0], (ast.Eq, ast.NotEq))
                and isinstance(node.left, ast.Name) and node.left.id in MARKER_VALUES
                and isinstance(node.comparators[0], ast.Constant)
                and isinstance(node.comparators[0].value, str)
                and node.comparators[0].value in MARKER_VALUES[node.left.id]):
            equal = environment[node.left.id] == node.comparators[0].value
            return equal if isinstance(node.ops[0], ast.Eq) else not equal
        raise ValueError(f"Review unsupported shared-pin marker: {marker}")

    return visit(ast.parse(marker, mode="eval").body)


def locked_pins(text):
    pins = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "--hash=")):
            continue
        match = re.fullmatch(r"([A-Za-z0-9._-]+)==([^;\s]+)(?:\s*;\s*(.*))?",
                             line.removesuffix("\\").rstrip())
        if not match:
            raise ValueError(f"Review unsupported lock entry: {line}")
        name, version, marker = match.groups()
        pins.setdefault(re.sub(r"[-_.]+", "-", name).lower(), []).append((version, marker))
    return pins


def environments():
    # Cover every platform class distinguished by the current shared-pin
    # markers, including the Intel-macOS and PyPy TLS exclusions. OTHER
    # representatives cover platforms not named by the equality predicates.
    for system, machine, implementation in itertools.product(
        ("linux", "darwin", "win32", "__other_platform__"),
        ("x86_64", "AMD64", "aarch64", "arm64", "__other_machine__"),
        ("CPython", "PyPy", "__OtherImplementation__"),
    ):
        yield {"sys_platform": system, "platform_machine": machine,
               "platform_python_implementation": implementation,
               "implementation_name": {"CPython": "cpython", "PyPy": "pypy"}.get(implementation, "__other_implementation__")}


def assert_compatible(first_text, second_text):
    first, second = locked_pins(first_text), locked_pins(second_text)
    for name in first.keys() & second.keys():
        for first_pin, second_pin in itertools.product(first[name], second[name]):
            for environment in environments():
                first_applies = marker_applies(first_pin[1], environment)
                second_applies = marker_applies(second_pin[1], environment)
                if first_applies and second_applies and first_pin[0] != second_pin[0]:
                    raise ValueError(
                        f"{name} pins conflict ({first_pin[0]} / {second_pin[0]}) on {environment}; "
                        "manually regenerate and qualify the held Russian Kitten lock with the TLS lock")


class SharedLockCompatibilityTests(unittest.TestCase):
    def test_checked_in_joint_install_pins_agree(self):
        assert_compatible((ROOT / "requirements-tls.lock").read_text(),
                          (ROOT / "requirements-russian-kitten.lock").read_text())

    def test_conflicting_linux_pin_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cffi pins conflict"):
            assert_compatible("cffi==2.1.2; sys_platform != 'darwin'\n", "cffi==2.1.1\n")

    def test_disjoint_platform_pins_are_allowed(self):
        assert_compatible("cffi==2.1.2; sys_platform != 'darwin'\n",
                          "cffi==2.1.1; sys_platform == 'darwin'\n")

    def test_intel_macos_and_pypy_exclusions_are_respected(self):
        tls = "(platform_machine != 'x86_64' and platform_python_implementation != 'PyPy') or (platform_python_implementation != 'PyPy' and sys_platform != 'darwin')"
        for environment in environments():
            expected = environment['platform_python_implementation'] != 'PyPy' and not (
                environment['sys_platform'] == 'darwin' and environment['platform_machine'] == 'x86_64')
            self.assertEqual(marker_applies(tls, environment), expected)

    def test_unknown_shared_marker_requires_review(self):
        with self.assertRaisesRegex(ValueError, "unsupported shared-pin marker"):
            assert_compatible("cffi==2.1.2; sys_platform in 'linux'\n", "cffi==2.1.1\n")

    def test_complement_of_named_machines_still_checks_pins(self):
        marker = " and ".join(f"platform_machine != '{machine}'" for machine in
                              ("x86_64", "AMD64", "aarch64", "arm64"))
        with self.assertRaisesRegex(ValueError, "cffi pins conflict"):
            assert_compatible(f"cffi==2.1.2; {marker}\n", "cffi==2.1.1\n")

    def test_new_platform_class_requires_review(self):
        with self.assertRaisesRegex(ValueError, "unsupported shared-pin marker"):
            assert_compatible("cffi==2.1.2; platform_machine == 'ppc64'\n", "cffi==2.1.1\n")

    def test_pin_name_normalization_and_duplicate_variants(self):
        with self.assertRaisesRegex(ValueError, "pycparser pins conflict"):
            assert_compatible("PyCParser==3.12; implementation_name != 'pypy'\n",
                              "pycparser==3.11; implementation_name == 'cpython'\n")


if __name__ == "__main__":
    unittest.main()
