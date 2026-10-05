import pytest
from pydantic import BaseModel, ValidationError

from hil.config.refs import Ref, ResourceRef


def test_parse_and_str():
    ref = ResourceRef.parse("rel1.6")
    assert ref == ResourceRef("rel1", "6")
    assert str(ref) == "rel1.6"


@pytest.mark.parametrize("text", ["rel1", ".6", "rel1.", "a.b.c", ""])
def test_parse_rejects_malformed(text):
    with pytest.raises(ValueError, match="invalid resource reference"):
        ResourceRef.parse(text)


class _Model(BaseModel):
    ref: Ref


def test_pydantic_accepts_string_and_instance():
    assert _Model(ref="ad3.awg1").ref == ResourceRef("ad3", "awg1")
    assert _Model(ref=ResourceRef("x", "1")).ref == ResourceRef("x", "1")


def test_pydantic_rejects_number():
    with pytest.raises(ValidationError, match="must be a string"):
        _Model(ref=1.5)


def test_serializes_as_string():
    assert _Model(ref="rel1.6").model_dump() == {"ref": "rel1.6"}
