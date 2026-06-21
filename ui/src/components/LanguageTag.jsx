const FLORES_TO_LABEL = {
  hin_Deva: 'हिंदी',
  tam_Taml: 'தமிழ்',
  tel_Telu: 'తెలుగు',
  mar_Deva: 'मराठी',
  pan_Guru: 'ਪੰਜਾਬੀ',
  eng_Latn: 'English',
}

export default function LanguageTag({ lang }) {
  const label = FLORES_TO_LABEL[lang] ?? lang
  return (
    <span className="language-tag" title={lang}>
      {label}
    </span>
  )
}
