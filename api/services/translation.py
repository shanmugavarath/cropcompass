"""
api/services/translation.py — IndicTrans2 translation service (English <-> Indic).

Two directions, selected by model:
  * "ai4bharat/indictrans2-indic-en-1B"  — Indic -> English  (used to normalise the
    Tamil SAU corpus to English, and to translate a farmer's query to English for retrieval)
  * "ai4bharat/indictrans2-en-indic-1B"  — English -> Indic  (used to translate the agent's
    English recommendation into the farmer's language for output)

Design notes
------------
* IndicTrans2 works best sentence-by-sentence, so each input is split into sentences,
  the sentences are translated in batches, then re-joined per input. This keeps long
  chunks (our 512-char RAG chunks) within the model's comfortable length.
* Uses IndicProcessor (IndicTransToolkit) for the required pre/post-processing.
* GPU is used automatically when available; the model loads once per instance.

FLORES-200 codes used here: eng_Latn, hin_Deva, tam_Taml, tel_Telu, mar_Deva, pan_Guru.

Smoke test:
    python -m api.services.translation --self-test
"""

from __future__ import annotations

import re
import signal
import sys
import threading

DEFAULT_EN_INDIC = "ai4bharat/indictrans2-en-indic-1B"
DEFAULT_INDIC_EN = "ai4bharat/indictrans2-indic-en-1B"

# Split on sentence enders incl. Devanagari danda (।) and newlines; keep it simple/robust.
_SENT_SPLIT = re.compile(r"(?<=[.!?।])\s+|\n+")
MAX_SENTENCE_CHARS = 500  # truncate sentences longer than this before translation
BATCH_TIMEOUT_SEC = 180   # skip a batch if it takes longer than this


def split_sentences(text: str) -> list[str]:
    """Split text into sentence-ish units for translation; never returns empty."""
    parts = [s.strip() for s in _SENT_SPLIT.split(text or "") if s and s.strip()]
    return parts or ([text.strip()] if text and text.strip() else [])


class TranslationService:
    SUPPORTED = {"eng_Latn", "hin_Deva", "tam_Taml", "tel_Telu", "mar_Deva", "pan_Guru"}

    def __init__(self, model_name: str = DEFAULT_EN_INDIC, device: str | None = None,
                 max_tokens: int = 256, num_beams: int = 5):
        # Imported here so the rest of the app doesn't pay the import cost unless translating.
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        try:
            from IndicTransToolkit.processor import IndicProcessor
        except ImportError:  # older toolkit layout
            from IndicTransToolkit import IndicProcessor  # type: ignore

        self._torch = torch
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.num_beams = num_beams
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        self.tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            model_name, trust_remote_code=True
        ).to(self.device)
        self.model.eval()
        self.ip = IndicProcessor(inference=True)

    # ---------------------------------------------------------------- core
    def _generate_batch(self, chunk: list[str], src_lang: str, tgt_lang: str) -> list[str]:
        """Translate one batch of sentences. Raises on failure."""
        pre = self.ip.preprocess_batch(chunk, src_lang=src_lang, tgt_lang=tgt_lang)
        inputs = self.tokenizer(
            pre, truncation=True, padding="longest",
            max_length=self.max_tokens, return_tensors="pt",
        ).to(self.device)
        with self._torch.no_grad():
            generated = self.model.generate(
                **inputs,
                max_new_tokens=self.max_tokens,
                num_beams=self.num_beams,
                num_return_sequences=1,
                early_stopping=True,
            )
        decoded = self.tokenizer.batch_decode(
            generated, skip_special_tokens=True, clean_up_tokenization_spaces=True,
        )
        return self.ip.postprocess_batch(decoded, lang=tgt_lang)

    def _generate_with_timeout(self, chunk: list[str], src_lang: str, tgt_lang: str,
                               timeout: int = BATCH_TIMEOUT_SEC) -> list[str] | None:
        """Run _generate_batch in a thread; return None on timeout/error."""
        result: list[str] = []
        error: list[Exception] = []
        self._last_error: Exception | None = None

        def _worker():
            try:
                result.extend(self._generate_batch(chunk, src_lang, tgt_lang))
            except Exception as e:
                error.append(e)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(timeout=timeout)
        if t.is_alive():
            self._last_error = None
            return None
        if error:
            self._last_error = error[0]
            return None
        self._last_error = None
        return result

    def translate_batch(self, texts: list[str], src_lang: str, tgt_lang: str,
                        batch_size: int = 32) -> list[str]:
        """Translate a list of texts src_lang -> tgt_lang. Sentence-aware + batched."""
        if src_lang == tgt_lang:
            return list(texts)

        # 1) explode each text into sentences, remember the slice that belongs to it
        spans: list[tuple[int, int]] = []
        flat: list[str] = []
        for t in texts:
            sents = split_sentences(t)
            spans.append((len(flat), len(flat) + len(sents)))
            flat.extend(sents)

        # sanitize: truncate very long sentences that cause beam-search to hang
        flat = [s[:MAX_SENTENCE_CHARS] for s in flat]

        # 2) translate the flat sentence list in batches
        n_batches = (len(flat) + batch_size - 1) // batch_size
        out: list[str] = []
        for i in range(0, len(flat), batch_size):
            chunk = flat[i:i + batch_size]
            batch_num = i // batch_size + 1
            max_chars = max((len(s) for s in chunk), default=0)
            print(f"    translate batch {batch_num}/{n_batches} "
                  f"({len(chunk)} sents, longest={max_chars} chars) ...",
                  file=sys.stderr, flush=True, end="")

            result = self._generate_with_timeout(chunk, src_lang, tgt_lang)
            if result is None:
                err = self._last_error
                if err:
                    print(f" ERROR ({type(err).__name__}: {err}) — skipping, using originals",
                          file=sys.stderr, flush=True)
                else:
                    print(f" TIMEOUT ({BATCH_TIMEOUT_SEC}s) — skipping, using originals",
                          file=sys.stderr, flush=True)
                out.extend(chunk)
            else:
                out.extend(result)
                print(" done", file=sys.stderr, flush=True)

        # 3) re-join sentences back into one string per input
        return [" ".join(out[a:b]).strip() for (a, b) in spans]

    def _translate(self, text: str, src_lang: str, tgt_lang: str) -> str:
        """Internal: translate a single text with explicit src/tgt langs."""
        return self.translate_batch([text], src_lang, tgt_lang)[0]

    def translate(self, text: str, tgt_lang: str) -> dict:
        """Translate English text to tgt_lang (FLORES-200 code).

        Returns {"translated": str, "lang": str}.
        Falls back to English if tgt_lang not in supported set.
        """
        if tgt_lang not in self.SUPPORTED or tgt_lang == "eng_Latn":
            return {"translated": text, "lang": "eng_Latn", "fallback": True}
        translated = self._translate(text, "eng_Latn", tgt_lang)
        return {"translated": translated, "lang": tgt_lang}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--model", default=DEFAULT_EN_INDIC)
    ap.add_argument("--tgt", default="hin_Deva")
    ap.add_argument("--text", default="Sow your rice seeds now and apply basal fertilizer.")
    args = ap.parse_args()
    svc = TranslationService(args.model)
    result = svc.translate(args.text, args.tgt)
    print(f"[eng_Latn -> {args.tgt}] {args.text!r}")
    print(f"-> {result['translated']}")
    print(f"   lang={result['lang']}")
