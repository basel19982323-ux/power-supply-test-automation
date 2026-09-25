"""Registry of available test types.

To add a new test: implement a TestType subclass in a module here and add its
class to REGISTRY. Nothing else in the app needs to change — the GUI, runner,
persistence, and reporting all read the test through the TestType interface.
"""
from .dynamic_output_response import DynamicOutputResponseTest
from .vds_ovp import VDSOVPTest
from .vds_turnoff import VDSTurnoffTest

# id -> TestType class
REGISTRY = {
    DynamicOutputResponseTest.id: DynamicOutputResponseTest,
    VDSTurnoffTest.id: VDSTurnoffTest,
    VDSOVPTest.id: VDSOVPTest,
}


def list_tests():
    """Return [(id, name, description), ...] for populating the Test dropdown."""
    return [(cls.id, cls.name, cls.description) for cls in REGISTRY.values()]


def get_test(test_id: str):
    """Instantiate a test type by id."""
    if test_id not in REGISTRY:
        raise KeyError(f"Unknown test type: {test_id!r}. "
                       f"Available: {list(REGISTRY)}")
    return REGISTRY[test_id]()


def default_test():
    """The test selected on first launch."""
    return DynamicOutputResponseTest()
