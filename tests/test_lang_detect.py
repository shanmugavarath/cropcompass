"""
tests/test_lang_detect.py — Language detection & routing tests.

All tests are fast (no ML model loading — lingua is lightweight).
"""

import time
import pytest
from api.services.lang_detect import detect_language, detect_with_codeswitching


class TestDetectLanguage:
    def test_hindi(self):
        assert detect_language("क्या मुझे अभी बुवाई करनी चाहिए?") == "hin_Deva"

    def test_tamil(self):
        assert detect_language("இப்போது விதைக்க வேண்டுமா?") == "tam_Taml"

    def test_telugu(self):
        assert detect_language("ఇప్పుడు విత్తనాలు వేయాలా?") == "tel_Telu"

    def test_marathi(self):
        assert detect_language("आता पेरणी करावी का?") == "mar_Deva"

    def test_punjabi(self):
        assert detect_language("ਕੀ ਮੈਨੂੰ ਹੁਣ ਬਿਜਾਈ ਕਰਨੀ ਚਾਹੀਦੀ ਹੈ?") == "pan_Guru"

    def test_english(self):
        assert detect_language("Should I sow now?") == "eng_Latn"

    def test_unknown_lang_fallback(self):
        assert detect_language("Bonjour le monde") == "eng_Latn"


class TestDetectWithCodeswitching:
    def test_hinglish_devanagari_dominant(self):
        # Devanagari chars (14) > Latin chars (3) → hin_Deva
        result = detect_with_codeswitching("क्या मुझे अभी sow करना चाहिए?")
        assert result == "hin_Deva"

    def test_hinglish_latin_dominant(self):
        # Latin chars (24) > Devanagari chars (4) → falls through to detect_language
        result = detect_with_codeswitching("क्या mujhe abhi sow karna chahiye?")
        assert result == "eng_Latn"

    def test_english_dominant_mixed(self):
        result = detect_with_codeswitching("Should I sow my rice now?")
        assert result == "eng_Latn"

    def test_pure_hindi_passthrough(self):
        result = detect_with_codeswitching("क्या मुझे अभी बुवाई करनी चाहिए?")
        assert result == "hin_Deva"

    def test_pure_english_passthrough(self):
        result = detect_with_codeswitching("When should I irrigate my field?")
        assert result == "eng_Latn"


class TestLatency:
    def test_detection_under_50ms(self):
        texts = [
            "क्या मुझे अभी बुवाई करनी चाहिए?",
            "இப்போது விதைக்க வேண்டுமா?",
            "Should I sow now?",
            "ఇప్పుడు విత్తనాలు వేయాలా?",
            "ਕੀ ਮੈਨੂੰ ਹੁਣ ਬਿਜਾਈ ਕਰਨੀ ਚਾਹੀਦੀ ਹੈ?",
        ]
        for text in texts:
            start = time.perf_counter()
            detect_language(text)
            elapsed_ms = (time.perf_counter() - start) * 1000
            assert elapsed_ms < 50, f"Detection took {elapsed_ms:.1f}ms for: {text[:30]}..."
