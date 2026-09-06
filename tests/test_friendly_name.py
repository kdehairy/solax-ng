import pytest

import solaxng.inverters as inverter


@pytest.mark.parametrize("name", inverter.__all__)
def test_friendly_name_is_non_empty_string(name):
    cls = getattr(inverter, name)
    friendly_name = cls.friendly_name()
    assert isinstance(friendly_name, str)
    assert friendly_name


def test_friendly_names_are_unique():
    friendly_names = [
        getattr(inverter, name).friendly_name() for name in inverter.__all__
    ]
    assert len(friendly_names) == len(set(friendly_names))
