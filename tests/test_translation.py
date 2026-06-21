"""
tests/test_translation.py — IndicTrans2 translation quality + contract tests.

Fast tests (no model): test_*_fallback, test_split_sentences
Slow tests (load model): marked @pytest.mark.slow — run with `pytest -m slow`
"""

import pytest
from api.services.translation import TranslationService, split_sentences

# ---- Unicode range helpers ----

UNICODE_RANGES = {
    "hin_Deva": (0x0900, 0x097F),  # Devanagari
    "mar_Deva": (0x0900, 0x097F),  # Devanagari (shared with Hindi)
    "tam_Taml": (0x0B80, 0x0BFF),  # Tamil
    "tel_Telu": (0x0C00, 0x0C7F),  # Telugu
    "pan_Guru": (0x0A00, 0x0A7F),  # Gurmukhi
}


def has_script(text: str, lang: str) -> bool:
    lo, hi = UNICODE_RANGES[lang]
    return any(lo <= ord(c) <= hi for c in text)


# ---- Unit tests (no model needed) ----

class TestSplitSentences:
    def test_english(self):
        assert split_sentences("Hello world. How are you?") == ["Hello world.", "How are you?"]

    def test_devanagari_danda(self):
        sents = split_sentences("पहला वाक्य। दूसरा वाक्य।")
        assert len(sents) == 2

    def test_empty(self):
        assert split_sentences("") == []
        assert split_sentences(None) == []

    def test_single_sentence(self):
        assert split_sentences("No period here") == ["No period here"]

    def test_newlines(self):
        sents = split_sentences("Line one\nLine two\nLine three")
        assert len(sents) == 3


class TestFallback:
    def test_unsupported_lang_fallback(self):
        svc = object.__new__(TranslationService)
        svc.SUPPORTED = TranslationService.SUPPORTED
        result = svc.translate("Apply fertilizer.", "xyz_Unknown")
        assert result["lang"] == "eng_Latn"
        assert result["translated"] == "Apply fertilizer."
        assert result["fallback"] is True

    def test_english_passthrough(self):
        svc = object.__new__(TranslationService)
        svc.SUPPORTED = TranslationService.SUPPORTED
        result = svc.translate("Irrigate now.", "eng_Latn")
        assert result["lang"] == "eng_Latn"
        assert result["translated"] == "Irrigate now."
        assert result["fallback"] is True


# ---- Slow tests (require model download + GPU/CPU) ----

@pytest.fixture(scope="module")
def svc():
    return TranslationService(device="cpu", num_beams=1)


@pytest.mark.slow
def test_hindi_translation(svc):
    result = svc.translate("Sow your rice seeds now.", "hin_Deva")
    assert result["lang"] == "hin_Deva"
    assert len(result["translated"]) > 5
    assert has_script(result["translated"], "hin_Deva")


@pytest.mark.slow
def test_tamil_translation(svc):
    result = svc.translate("Apply urea fertilizer at 25 kg per acre.", "tam_Taml")
    assert result["lang"] == "tam_Taml"
    assert has_script(result["translated"], "tam_Taml")


@pytest.mark.slow
def test_telugu_translation(svc):
    result = svc.translate("Irrigate the field before sowing.", "tel_Telu")
    assert result["lang"] == "tel_Telu"
    assert has_script(result["translated"], "tel_Telu")


@pytest.mark.slow
def test_marathi_translation(svc):
    result = svc.translate("Use organic compost for better yield.", "mar_Deva")
    assert result["lang"] == "mar_Deva"
    assert has_script(result["translated"], "mar_Deva")


@pytest.mark.slow
def test_punjabi_translation(svc):
    result = svc.translate("Harvest wheat when the grain is hard.", "pan_Guru")
    assert result["lang"] == "pan_Guru"
    assert has_script(result["translated"], "pan_Guru")


@pytest.mark.slow
def test_translation_latency(svc):
    import time
    text = "Apply 25 kg urea per acre at the time of sowing. Ensure adequate soil moisture."
    start = time.perf_counter()
    svc.translate("Sow now.", "hin_Deva")
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0, f"Translation took {elapsed:.1f}s — target is < 3s on CPU"
