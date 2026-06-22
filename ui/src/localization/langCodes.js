/**
 * Shared FLORES-200 ↔ BCP47 / Web Speech API mappings.
 * Imported by useSpeechInput and useSpeech so the mapping lives in one place.
 */

/** FLORES-200 → BCP47 language tag (for lang= attributes and speechSynthesis voice matching) */
export const FLORES_TO_BCP47 = {
  hin_Deva: 'hi',
  mar_Deva: 'mr',
  tam_Taml: 'ta',
  tel_Telu: 'te',
  pan_Guru: 'pa',
  ben_Beng: 'bn',
  kan_Knda: 'kn',
  mal_Mlym: 'ml',
  eng_Latn: 'en',
}

/** FLORES-200 → BCP47 locale tag used for SpeechRecognition.lang (includes country code) */
export const FLORES_TO_SPEECH_LOCALE = {
  hin_Deva: 'hi-IN',
  mar_Deva: 'mr-IN',
  tam_Taml: 'ta-IN',
  tel_Telu: 'te-IN',
  pan_Guru: 'pa-IN',
  ben_Beng: 'bn-IN',
  kan_Knda: 'kn-IN',
  mal_Mlym: 'ml-IN',
  eng_Latn: 'en-IN',
}
