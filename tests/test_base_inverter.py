import pytest

from solaxng.discovery import REGISTRY
from solaxng.inverter import Inverter


def test_all_registered_inverters_inherit_from_base():
    assert REGISTRY
    for i in REGISTRY:
        assert issubclass(i, Inverter)


def test_all_registered_inverters_declare_an_endpoint():
    """A model declaring none is never probed, so it silently vanishes."""
    for i in REGISTRY:
        assert i.endpoints, i.__name__


def test_unimplemented_response_decoder():
    with pytest.raises(NotImplementedError):
        Inverter.response_decoder()
