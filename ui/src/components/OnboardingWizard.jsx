import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'

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

const SOIL_OPTIONS = [
  { value: 'clay',      icon: '🟫', label: 'Clay',      desc: 'Heavy, water-retaining' },
  { value: 'loam',      icon: '🌱', label: 'Loam',      desc: 'Balanced, fertile' },
  { value: 'sandy',     icon: '🏜️', label: 'Sandy',     desc: 'Light, fast-draining' },
  { value: 'clay_loam', icon: '🪨', label: 'Clay Loam', desc: 'Moderately heavy' },
  { value: 'silt_loam', icon: '💧', label: 'Silt Loam', desc: 'Moisture-retaining' },
]

const STAGE_OPTIONS = [
  { value: 'sowing',     label: 'Sowing',     desc: 'Seed planting' },
  { value: 'vegetative', label: 'Vegetative', desc: 'Leaf & stem growth' },
  { value: 'flowering',  label: 'Flowering',  desc: 'Bloom & pollination' },
  { value: 'maturity',   label: 'Maturity',   desc: 'Harvest ready' },
]

const COMMON_CROPS = [
  'Rice (Basmati)', 'Rice (IR-36)', 'Wheat (HD-2967)', 'Wheat (GW-322)',
  'Soybean (JS-335)', 'Cotton (Bt)', 'Sugarcane', 'Maize (HQPM-1)',
  'Groundnut (TAG-24)', 'Tomato', 'Onion', 'Potato', 'Turmeric',
  'Chilli', 'Bajra (HHB-67)', 'Jowar', 'Tur (ICPL-87)', 'Gram (JG-11)',
  'Banana', 'Mango', 'Grapes',
]

const LANG_OPTIONS = [
  {
    value: 'hin_Deva', native: 'हिंदी',  label: 'Hindi',
    font: 'var(--font-deva)', bcp47: 'hi',
    preview: 'नमस्ते, किसान! CropCompass में आपका स्वागत है।',
  },
  {
    value: 'mar_Deva', native: 'मराठी',  label: 'Marathi',
    font: 'var(--font-deva)', bcp47: 'mr',
    preview: 'नमस्कार, शेतकरी! CropCompass मध्ये आपले स्वागत आहे।',
  },
  {
    value: 'tam_Taml', native: 'தமிழ்',  label: 'Tamil',
    font: 'var(--font-taml)', bcp47: 'ta',
    preview: 'வணக்கம், விவசாயி! CropCompass-இல் வரவேற்கிறோம்.',
  },
  {
    value: 'tel_Telu', native: 'తెలుగు', label: 'Telugu',
    font: 'var(--font-telu)', bcp47: 'te',
    preview: 'నమస్కారం, రైతు! CropCompass కి స్వాగతం.',
  },
  {
    value: 'pan_Guru', native: 'ਪੰਜਾਬੀ', label: 'Punjabi',
    font: 'var(--font-guru)', bcp47: 'pa',
    preview: 'ਸਤਿ ਸ੍ਰੀ ਅਕਾਲ, ਕਿਸਾਨ! CropCompass ਵਿੱਚ ਜੀ ਆਇਆਂ ਨੂੰ।',
  },
  {
    value: 'eng_Latn', native: 'English', label: 'English',
    font: 'var(--font-body)', bcp47: 'en',
    preview: 'Hello, Farmer! Welcome to CropCompass.',
  },
]

const STEP_LABELS = ['Location', 'Farm Details', 'Language']

export default function OnboardingWizard() {
  const navigate = useNavigate()
  const [step, setStep] = useState(1)
  const [apiDistricts, setApiDistricts] = useState([])
  const [formData, setFormData] = useState({
    state: '', district: '', soil_type: '',
    crop_variety: '', growth_stage: '', lang_pref: '',
  })
  const [errors, setErrors] = useState({})
  const [submitting, setSubmitting] = useState(false)
  const [serverError, setServerError] = useState('')

  useEffect(() => {
    client.get('/api/districts')
      .then(r => setApiDistricts(r.data.districts ?? []))
      .catch(() => {})
  }, [])

  const stateDistricts = formData.state ? (STATE_DISTRICTS[formData.state] ?? []) : []

  function setField(field, value) {
    setFormData(prev => ({ ...prev, [field]: value }))
    if (errors[field]) setErrors(prev => { const e = { ...prev }; delete e[field]; return e })
  }

  function validateStep1() {
    const errs = {}
    if (!formData.state) errs.state = 'Please select your state.'
    if (!formData.district) errs.district = 'Please select your district.'
    else if (apiDistricts.length > 0 && !apiDistricts.includes(formData.district)) {
      errs.district = 'District not in advisory network. Please select another.'
    }
    return errs
  }

  function validateStep2() {
    const errs = {}
    if (!formData.soil_type) errs.soil_type = 'Please select your soil type.'
    if (!formData.crop_variety || formData.crop_variety.trim().length < 2) {
      errs.crop_variety = 'Please enter a crop variety (minimum 2 characters).'
    }
    if (!formData.growth_stage) errs.growth_stage = 'Please select the growth stage.'
    return errs
  }

  function nextStep() {
    const errs = step === 1 ? validateStep1() : validateStep2()
    if (Object.keys(errs).length) { setErrors(errs); return }
    setErrors({})
    setStep(s => s + 1)
  }

  async function handleSubmit() {
    if (!formData.lang_pref) {
      setErrors({ lang_pref: 'Please select your preferred language.' })
      return
    }
    setSubmitting(true)
    setServerError('')
    try {
      const { data } = await client.post('/api/profile', {
        district:     formData.district,
        soil_type:    formData.soil_type,
        crop_variety: formData.crop_variety.trim(),
        growth_stage: formData.growth_stage,
        lang_pref:    formData.lang_pref,
      })
      localStorage.setItem('farmer_id', data.farmer_id)
      console.log('navigating to chat...')
      navigate('/chat')
    } catch (err) {
      const msg = err.response?.data?.detail ?? 'Something went wrong. Please try again.'
      setServerError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  const selectedLang = LANG_OPTIONS.find(l => l.value === formData.lang_pref)
  const progressPct  = ((step - 1) / STEP_LABELS.length) * 100

  return (
    <div className="wizard-layout">
      <div className="wizard-header">
        <h1>CropCompass</h1>
        <p>Set up your profile to get personalised crop advice</p>
      </div>

      <div className="wizard-progress">
        <div className="wizard-progress__track">
          <div className="wizard-progress__fill" style={{ width: `${progressPct}%` }} />
        </div>
        <div className="wizard-progress__labels">
          {STEP_LABELS.map((label, i) => (
            <span
              key={label}
              style={{ color: i + 1 <= step ? 'var(--color-green)' : undefined, fontWeight: i + 1 === step ? 500 : undefined }}
            >
              {label}
            </span>
          ))}
        </div>
      </div>

      <div className="wizard-card">
        {step === 1 && (
          <Step1
            formData={formData}
            errors={errors}
            setField={setField}
            stateDistricts={stateDistricts}
            onNext={nextStep}
          />
        )}
        {step === 2 && (
          <Step2
            formData={formData}
            errors={errors}
            setField={setField}
            onBack={() => setStep(1)}
            onNext={nextStep}
          />
        )}
        {step === 3 && (
          <Step3
            formData={formData}
            errors={errors}
            setField={setField}
            selectedLang={selectedLang}
            serverError={serverError}
            submitting={submitting}
            onBack={() => setStep(2)}
            onSubmit={handleSubmit}
          />
        )}
      </div>
    </div>
  )
}

function Step1({ formData, errors, setField, stateDistricts, onNext }) {
  return (
    <>
      <h2>Your Location</h2>
      <p className="wizard-card__subtitle">
        We use your district to fetch local weather and soil data.
      </p>

      <div className="field-group">
        <div className="field">
          <label htmlFor="state-select">State</label>
          <select
            id="state-select"
            value={formData.state}
            onChange={e => { setField('state', e.target.value); setField('district', '') }}
            aria-invalid={!!errors.state}
          >
            <option value="">— Select state —</option>
            {Object.keys(STATE_DISTRICTS).sort().map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          {errors.state && <span className="field-error" role="alert">{errors.state}</span>}
        </div>

        <div className="field">
          <label htmlFor="district-select">District</label>
          <select
            id="district-select"
            value={formData.district}
            onChange={e => setField('district', e.target.value)}
            disabled={!formData.state}
            aria-invalid={!!errors.district}
          >
            <option value="">— Select district —</option>
            {stateDistricts.map(d => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          {errors.district && <span className="field-error" role="alert">{errors.district}</span>}
        </div>
      </div>

      <div className="wizard-nav">
        <button className="btn-next" onClick={onNext}>Next: Farm Details →</button>
      </div>
    </>
  )
}

function Step2({ formData, errors, setField, onBack, onNext }) {
  return (
    <>
      <h2>Your Farm</h2>
      <p className="wizard-card__subtitle">
        This helps us tailor soil and fertiliser advice.
      </p>

      <div className="field-group">
        <div className="field">
          <label>Soil Type</label>
          <div className="soil-grid" role="radiogroup" aria-label="Soil type">
            {SOIL_OPTIONS.map(opt => (
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
          <label htmlFor="crop-input">Crop Variety</label>
          <input
            id="crop-input"
            type="text"
            list="crop-list"
            placeholder="e.g. Soybean JS-335"
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
          <label>Growth Stage</label>
          <div className="stage-grid" role="radiogroup" aria-label="Growth stage">
            {STAGE_OPTIONS.map(opt => (
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

      <div className="wizard-nav">
        <button className="btn-back" onClick={onBack}>← Back</button>
        <button className="btn-next" onClick={onNext}>Next: Language →</button>
      </div>
    </>
  )
}

function Step3({ formData, errors, setField, selectedLang, serverError, submitting, onBack, onSubmit }) {
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

      {serverError && (
        <div className="server-error" role="alert">{serverError}</div>
      )}

      <div className="wizard-nav">
        <button className="btn-back" onClick={onBack}>← Back</button>
        <button
          className="btn-submit"
          onClick={onSubmit}
          disabled={submitting}
        >
          {submitting ? 'Setting up…' : 'Start Advising →'}
        </button>
      </div>
    </>
  )
}
