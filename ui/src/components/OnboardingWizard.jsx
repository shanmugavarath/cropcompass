import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import STRINGS from '../localization/index'

// ── Static data ───────────────────────────────────────────────────────────────

const STATE_DISTRICTS = {
  'Andhra Pradesh':  ['Vijayawada', 'Visakhapatnam'],
  'Bihar':           ['Patna'],
  'Chhattisgarh':    ['Raipur'],
  'Gujarat':         ['Ahmedabad', 'Surat', 'Vadodara'],
  'Jharkhand':       ['Ranchi'],
  'Karnataka':       ['Bangalore'],
  'Madhya Pradesh':  ['Bhopal', 'Indore'],
  'Maharashtra':     ['Amravati', 'Aurangabad', 'Mumbai', 'Nagpur', 'Nashik', 'Pune'],
  'Rajasthan':       ['Jaipur'],
  'Tamil Nadu':      ['Chennai', 'Coimbatore'],
  'Telangana':       ['Hyderabad'],
  'Uttar Pradesh':   ['Lucknow', 'Varanasi'],
  'West Bengal':     ['Kolkata'],
}

// value + icon only — labels come from the localization strings
const SOIL_VALUES = [
  { value: 'clay',      icon: '🟫' },
  { value: 'loam',      icon: '🌱' },
  { value: 'sandy',     icon: '🏜️'  },
  { value: 'clay_loam', icon: '🪨' },
  { value: 'silt_loam', icon: '💧' },
]
const SOIL_KEYS = ['soilClay', 'soilLoam', 'soilSandy', 'soilClayLoam', 'soilSiltLoam']

const STAGE_VALUES = ['sowing', 'vegetative', 'flowering', 'maturity']
const STAGE_KEYS   = ['stageSowing', 'stageVegetative', 'stageFlowering', 'stageMaturity']

const COMMON_CROPS = [
  'Rice (Basmati)', 'Rice (IR-36)', 'Wheat (HD-2967)', 'Wheat (GW-322)',
  'Soybean (JS-335)', 'Cotton (Bt)', 'Sugarcane', 'Maize (HQPM-1)',
  'Groundnut (TAG-24)', 'Tomato', 'Onion', 'Potato', 'Turmeric',
  'Chilli', 'Bajra (HHB-67)', 'Jowar', 'Tur (ICPL-87)', 'Gram (JG-11)',
  'Banana', 'Mango', 'Grapes',
]

const LANG_OPTIONS = [
  {
    value: 'hin_Deva', native: 'हिंदी',   label: 'Hindi',
    font: 'var(--font-deva)', bcp47: 'hi',
    preview: 'नमस्ते, किसान! CropCompass में आपका स्वागत है।',
  },
  {
    value: 'mar_Deva', native: 'मराठी',   label: 'Marathi',
    font: 'var(--font-deva)', bcp47: 'mr',
    preview: 'नमस्कार, शेतकरी! CropCompass मध्ये आपले स्वागत आहे।',
  },
  {
    value: 'tam_Taml', native: 'தமிழ்',   label: 'Tamil',
    font: 'var(--font-taml)', bcp47: 'ta',
    preview: 'வணக்கம், விவசாயி! CropCompass-இல் வரவேற்கிறோம்.',
  },
  {
    value: 'tel_Telu', native: 'తెలుగు',  label: 'Telugu',
    font: 'var(--font-telu)', bcp47: 'te',
    preview: 'నమస్కారం, రైతు! CropCompass కి స్వాగతం.',
  },
  {
    value: 'pan_Guru', native: 'ਪੰਜਾਬੀ',  label: 'Punjabi',
    font: 'var(--font-guru)', bcp47: 'pa',
    preview: 'ਸਤਿ ਸ੍ਰੀ ਅਕਾਲ, ਕਿਸਾਨ! CropCompass ਵਿੱਚ ਜੀ ਆਇਆਂ ਨੂੰ।',
  },
  {
    value: 'ben_Beng', native: 'বাংলা',   label: 'Bengali',
    font: 'var(--font-beng)', bcp47: 'bn',
    preview: 'নমস্কার, কৃষক! CropCompass-এ আপনাকে স্বাগতম।',
  },
  {
    value: 'kan_Knda', native: 'ಕನ್ನಡ',   label: 'Kannada',
    font: 'var(--font-knda)', bcp47: 'kn',
    preview: 'ನಮಸ್ಕಾರ, ರೈತ! CropCompass-ಗೆ ಸ್ವಾಗತ.',
  },
  {
    value: 'mal_Mlym', native: 'മലയാളം', label: 'Malayalam',
    font: 'var(--font-mlym)', bcp47: 'ml',
    preview: 'നമസ്കാരം, കർഷകൻ! CropCompass-ലേക്ക് സ്വാഗതം.',
  },
  {
    value: 'eng_Latn', native: 'English',  label: 'English',
    font: 'var(--font-body)', bcp47: 'en',
    preview: 'Hello, Farmer! Welcome to CropCompass.',
  },
]

// ── Wizard ────────────────────────────────────────────────────────────────────

export default function OnboardingWizard() {
  const navigate = useNavigate()
  const [step, setStep] = useState(1)
  const [apiDistricts, setApiDistricts] = useState([])
  const [formData, setFormData] = useState({
    lang_pref: '', name: '', phone: '',
    state: '', district: '',
    soil_type: '', crop_variety: '', growth_stage: '',
  })
  const [errors, setErrors] = useState({})
  const [submitting, setSubmitting] = useState(false)
  const [serverError, setServerError] = useState('')

  useEffect(() => {
    client.get('/api/districts')
      .then(r => setApiDistricts(r.data.districts ?? []))
      .catch(() => {})
  }, [])

  // Derive localized strings and selected language metadata
  const t = STRINGS[formData.lang_pref] ?? STRINGS['eng_Latn']
  const selectedLang = LANG_OPTIONS.find(l => l.value === formData.lang_pref)
  const stateDistricts = formData.state ? (STATE_DISTRICTS[formData.state] ?? []) : []
  const stepLabels = [t.stepLang, t.stepIdentity, t.stepLocation, t.stepFarm]
  const progressPct = ((step - 1) / stepLabels.length) * 100

  function setField(field, value) {
    setFormData(prev => ({ ...prev, [field]: value }))
    if (errors[field]) setErrors(prev => { const e = { ...prev }; delete e[field]; return e })
  }

  function validateStep1() {
    if (!formData.lang_pref) return { lang_pref: 'Please select your preferred language.' }
    return {}
  }

  function validateStep2() {
    return {}
  }

  function validateStep3() {
    const errs = {}
    if (!formData.state) errs.state = t.errorState
    if (!formData.district) errs.district = t.errorDistrict
    else if (apiDistricts.length > 0 && !apiDistricts.includes(formData.district)) {
      errs.district = t.errorDistrictNetwork
    }
    return errs
  }

  function validateStep4() {
    const errs = {}
    if (!formData.soil_type) errs.soil_type = t.errorSoil
    if (!formData.crop_variety || formData.crop_variety.trim().length < 2) errs.crop_variety = t.errorCrop
    if (!formData.growth_stage) errs.growth_stage = t.errorStage
    return errs
  }

  function nextStep() {
    const errs = step === 1 ? validateStep1()
                : step === 2 ? validateStep2()
                : validateStep3()
    if (Object.keys(errs).length) { setErrors(errs); return }
    setErrors({})
    setStep(s => s + 1)
  }

  async function handleSubmit() {
    const errs = validateStep4()
    if (Object.keys(errs).length) { setErrors(errs); return }
    setSubmitting(true)
    setServerError('')
    try {
      const { data } = await client.post('/api/profile', {
        name:         formData.name.trim(),
        phone:        formData.phone.trim(),
        state:        formData.state,
        district:     formData.district,
        soil_type:    formData.soil_type,
        crop_variety: formData.crop_variety.trim(),
        growth_stage: formData.growth_stage,
        lang_pref:    formData.lang_pref,
      })
      localStorage.setItem('farmer_id', data.farmer_id)
      navigate('/chat')
    } catch (err) {
      const detail = err.response?.data?.detail
      const msg = Array.isArray(detail)
        ? detail.map(e => e.msg ?? String(e)).join(' · ')
        : (typeof detail === 'string' ? detail : 'Something went wrong. Please try again.')
      setServerError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="wizard-layout">
      <div className="wizard-header">
        <h1>CropCompass</h1>
        <p lang={selectedLang?.bcp47} style={{ fontFamily: selectedLang?.font }}>
          {t.wizardSubtitle}
        </p>
      </div>

      <div className="wizard-progress">
        <div className="wizard-progress__track">
          <div className="wizard-progress__fill" style={{ width: `${progressPct}%` }} />
        </div>
        <div className="wizard-progress__labels">
          {stepLabels.map((label, i) => (
            <span
              key={i}
              lang={selectedLang?.bcp47}
              style={{
                color:      i + 1 <= step ? 'var(--color-green)' : undefined,
                fontWeight: i + 1 === step ? 500 : undefined,
                fontFamily: selectedLang?.font,
              }}
            >
              {label}
            </span>
          ))}
        </div>
      </div>

      <div className="wizard-card">
        {step === 1 && (
          <StepLang
            formData={formData}
            errors={errors}
            setField={setField}
            selectedLang={selectedLang}
            onNext={nextStep}
          />
        )}
        {step === 2 && (
          <StepIdentity
            formData={formData}
            errors={errors}
            setField={setField}
            selectedLang={selectedLang}
            t={t}
            onBack={() => setStep(1)}
            onNext={nextStep}
          />
        )}
        {step === 3 && (
          <StepLocation
            formData={formData}
            errors={errors}
            setField={setField}
            stateDistricts={stateDistricts}
            selectedLang={selectedLang}
            t={t}
            onBack={() => setStep(2)}
            onNext={nextStep}
          />
        )}
        {step === 4 && (
          <StepFarm
            formData={formData}
            errors={errors}
            setField={setField}
            selectedLang={selectedLang}
            t={t}
            serverError={serverError}
            submitting={submitting}
            onBack={() => setStep(3)}
            onSubmit={handleSubmit}
          />
        )}
      </div>
    </div>
  )
}

// ── Step 1: Language selection (always in English — user hasn't chosen yet) ───

function StepLang({ formData, errors, setField, selectedLang, onNext }) {
  return (
    <>
      <h2>Your Language</h2>
      <p className="wizard-card__subtitle">
        Choose the language for your crop advisory messages.
      </p>

      <div className="lang-grid" role="radiogroup" aria-label="Preferred language">
        {LANG_OPTIONS.map(opt => (
          <div key={opt.value} className="lang-option">
            <input
              type="radio"
              id={`lang-${opt.value}`}
              name="lang_pref"
              value={opt.value}
              checked={formData.lang_pref === opt.value}
              onChange={() => setField('lang_pref', opt.value)}
            />
            <label htmlFor={`lang-${opt.value}`}>
              <span
                className="lang-option__native"
                lang={opt.bcp47}
                style={{ fontFamily: opt.font }}
              >
                {opt.native}
              </span>
              <span className="lang-option__label">{opt.label}</span>
            </label>
          </div>
        ))}
      </div>

      {errors.lang_pref && (
        <span className="field-error" role="alert" style={{ display: 'block', marginBottom: 12 }}>
          {errors.lang_pref}
        </span>
      )}

      {selectedLang && (
        <div
          className="lang-preview"
          lang={selectedLang.bcp47}
          style={{ fontFamily: selectedLang.font }}
          aria-label="Language preview"
        >
          {selectedLang.preview}
        </div>
      )}

      <div className="wizard-nav">
        <button className="btn-next" onClick={onNext}>Next: Your Details →</button>
      </div>
    </>
  )
}

// ── Step 2: Identity — name + phone, rendered in the chosen language ─────────

function StepIdentity({ formData, errors, setField, selectedLang, t, onBack, onNext }) {
  const langAttr   = selectedLang?.bcp47
  const fontFamily = selectedLang?.font

  return (
    <div lang={langAttr} style={{ fontFamily }}>
      <h2>{t.identityTitle}</h2>
      <p className="wizard-card__subtitle">{t.identitySubtitle}</p>

      <div className="field-group">
        <div className="field">
          <label htmlFor="name-input">
            {t.nameLabel} <span className="field-optional">{t.optional}</span>
          </label>
          <input
            id="name-input"
            type="text"
            placeholder={t.namePlaceholder}
            value={formData.name}
            onChange={e => setField('name', e.target.value)}
            autoComplete="name"
          />
        </div>

        <div className="field">
          <label htmlFor="phone-input">
            {t.phoneLabel} <span className="field-optional">{t.optional}</span>
          </label>
          <input
            id="phone-input"
            type="tel"
            inputMode="numeric"
            placeholder={t.phonePlaceholder}
            value={formData.phone}
            onChange={e => setField('phone', e.target.value.replace(/\D/g, '').slice(0, 10))}
            autoComplete="tel"
            maxLength={10}
          />
        </div>
      </div>

      <div className="wizard-nav">
        <button className="btn-back" onClick={onBack}>{t.backBtn}</button>
        <button className="btn-next" onClick={onNext}>{t.nextIdentityBtn}</button>
      </div>
    </div>
  )
}

// ── Step 3: Location — rendered in the chosen language ───────────────────────

function StepLocation({ formData, errors, setField, stateDistricts, selectedLang, t, onBack, onNext }) {
  const langAttr   = selectedLang?.bcp47
  const fontFamily = selectedLang?.font

  return (
    <div lang={langAttr} style={{ fontFamily }}>
      <h2>{t.locationTitle}</h2>
      <p className="wizard-card__subtitle">{t.locationSubtitle}</p>

      <div className="field-group">
        <div className="field">
          <label htmlFor="state-select">{t.stateLabel}</label>
          <select
            id="state-select"
            value={formData.state}
            onChange={e => { setField('state', e.target.value); setField('district', '') }}
            aria-invalid={!!errors.state}
          >
            <option value="">{t.statePlaceholder}</option>
            {Object.keys(STATE_DISTRICTS).sort().map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          {errors.state && <span className="field-error" role="alert">{errors.state}</span>}
        </div>

        <div className="field">
          <label htmlFor="district-select">{t.districtLabel}</label>
          <select
            id="district-select"
            value={formData.district}
            onChange={e => setField('district', e.target.value)}
            disabled={!formData.state}
            aria-invalid={!!errors.district}
          >
            <option value="">{t.districtPlaceholder}</option>
            {stateDistricts.map(d => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          {errors.district && <span className="field-error" role="alert">{errors.district}</span>}
        </div>
      </div>

      <div className="wizard-nav">
        <button className="btn-back" onClick={onBack}>{t.backBtn}</button>
        <button className="btn-next" onClick={onNext}>{t.nextLocationBtn}</button>
      </div>
    </div>
  )
}

// ── Step 4: Farm details — rendered in the chosen language ───────────────────

function StepFarm({ formData, errors, setField, selectedLang, t, serverError, submitting, onBack, onSubmit }) {
  const langAttr   = selectedLang?.bcp47
  const fontFamily = selectedLang?.font

  const soilOptions  = SOIL_VALUES.map((s, i) => ({ ...s, ...t[SOIL_KEYS[i]] }))
  const stageOptions = STAGE_VALUES.map((v, i) => ({ value: v, ...t[STAGE_KEYS[i]] }))

  return (
    <div lang={langAttr} style={{ fontFamily }}>
      <h2>{t.farmTitle}</h2>
      <p className="wizard-card__subtitle">{t.farmSubtitle}</p>

      <div className="field-group">
        <div className="field">
          <label>{t.soilLabel}</label>
          <div className="soil-grid" role="radiogroup" aria-label={t.soilLabel}>
            {soilOptions.map(opt => (
              <div key={opt.value} className="soil-radio">
                <input
                  type="radio"
                  id={`soil-${opt.value}`}
                  name="soil_type"
                  value={opt.value}
                  checked={formData.soil_type === opt.value}
                  onChange={() => setField('soil_type', opt.value)}
                />
                <label htmlFor={`soil-${opt.value}`}>
                  <span className="soil-icon" aria-hidden="true">{opt.icon}</span>
                  <span>{opt.label}</span>
                  <span className="soil-desc">{opt.desc}</span>
                </label>
              </div>
            ))}
          </div>
          {errors.soil_type && <span className="field-error" role="alert">{errors.soil_type}</span>}
        </div>

        <div className="field">
          <label htmlFor="crop-input">{t.cropLabel}</label>
          <input
            id="crop-input"
            type="text"
            list="crop-list"
            placeholder={t.cropPlaceholder}
            value={formData.crop_variety}
            onChange={e => setField('crop_variety', e.target.value)}
            aria-invalid={!!errors.crop_variety}
            autoComplete="off"
          />
          <datalist id="crop-list">
            {COMMON_CROPS.map(c => <option key={c} value={c} />)}
          </datalist>
          {errors.crop_variety && <span className="field-error" role="alert">{errors.crop_variety}</span>}
        </div>

        <div className="field">
          <label>{t.stageLabel}</label>
          <div className="stage-grid" role="radiogroup" aria-label={t.stageLabel}>
            {stageOptions.map(opt => (
              <div key={opt.value} className="stage-radio">
                <input
                  type="radio"
                  id={`stage-${opt.value}`}
                  name="growth_stage"
                  value={opt.value}
                  checked={formData.growth_stage === opt.value}
                  onChange={() => setField('growth_stage', opt.value)}
                />
                <label htmlFor={`stage-${opt.value}`}>
                  <span>{opt.label}</span>
                  <span className="stage-desc">{opt.desc}</span>
                </label>
              </div>
            ))}
          </div>
          {errors.growth_stage && <span className="field-error" role="alert">{errors.growth_stage}</span>}
        </div>
      </div>

      {serverError && (
        <div className="server-error" role="alert">{serverError}</div>
      )}

      <div className="wizard-nav">
        <button className="btn-back" onClick={onBack}>{t.backBtn}</button>
        <button
          className="btn-submit"
          onClick={onSubmit}
          disabled={submitting}
        >
          {submitting ? t.submittingBtn : t.submitBtn}
        </button>
      </div>
    </div>
  )
}
