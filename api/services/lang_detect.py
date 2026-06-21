"""
api/services/lang_detect.py — Language detection & routing for farmer queries.

Uses lingua-py to detect the language of incoming text and return a FLORES-200
code. Member 3 calls detect_with_codeswitching() in AgentRunner.run() when
farmer.lang_pref is not set.

Supported: eng_Latn, hin_Deva, tam_Taml, tel_Telu, mar_Deva, pan_Guru.
Fallback: eng_Latn for unrecognized input.
"""

from lingua import Language, LanguageDetectorBuilder

LINGUA_TO_FLORES = {
    Language.HINDI:   "hin_Deva",
    Language.TAMIL:   "tam_Taml",
    Language.TELUGU:  "tel_Telu",
    Language.MARATHI: "mar_Deva",
    Language.PUNJABI: "pan_Guru",
    Language.ENGLISH: "eng_Latn",
}

_detector = LanguageDetectorBuilder.from_languages(
    Language.ENGLISH,
    Language.HINDI,
    Language.TAMIL,
    Language.TELUGU,
    Language.MARATHI,
    Language.PUNJABI,
).build()


def detect_language(text: str) -> str:
    """Returns FLORES-200 code for the detected language. Defaults to eng_Latn."""
    lang = _detector.detect_language_of(text)
    return LINGUA_TO_FLORES.get(lang, "eng_Latn")


def detect_with_codeswitching(text: str) -> str:
    """Handles Hinglish / mixed-script text.

    If Devanagari characters outnumber Latin letters, classify as Hindi.
    Otherwise fall through to detect_language().
    """
    devanagari = sum(1 for c in text if 'ऀ' <= c <= 'ॿ')
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    if devanagari > latin:
        return "hin_Deva"
    return detect_language(text)
