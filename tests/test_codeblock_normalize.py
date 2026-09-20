import pytest
from websieve.clean.normalize import normalize

def test_normalize_preserves_fenced_code_block_indentation():
    src = "```python\ndef hello():\n    print('hi')\n    if x:\n        y()\n```"
    result = normalize(src)
    expected = "```python\ndef hello():\n    print('hi')\n    if x:\n        y()\n```"
    assert result == expected

def test_normalize_preserves_tilde_fenced_code_block():
    src = "~~~bash\n  git clone url\n    cd repo\n~~~"
    result = normalize(src)
    expected = "~~~bash\n  git clone url\n    cd repo\n~~~"
    assert result == expected

def test_normalize_collapses_regular_prose():
    src = "   This   is   a    test   \n\n\n\n   second   line   "
    result = normalize(src)
    assert result == "This is a test\n\nsecond line"
