const eng_Latn = {
  wizardSubtitle: 'Set up your profile to get personalised crop advice',
  stepLang:     'Language',
  stepLocation: 'Location',
  stepFarm:     'Farm Details',

  stepIdentity:  'Your Details',
  optional:      '(optional)',

  identityTitle:    'Your Details',
  identitySubtitle: 'This helps us personalise your advisory experience.',
  nameLabel:        'Your Name',
  namePlaceholder:  'e.g. Rameshwar',
  phoneLabel:       'Phone Number',
  phonePlaceholder: '10-digit mobile number',
  nextIdentityBtn:  'Next: Your Location →',

  locationTitle:        'Your Location',
  locationSubtitle:     'We use your district to fetch local weather and soil data.',
  stateLabel:           'State',
  statePlaceholder:     '— Select state —',
  districtLabel:        'District',
  districtPlaceholder:  '— Select district —',
  errorState:           'Please select your state.',
  errorDistrict:        'Please select your district.',
  errorDistrictNetwork: 'District not in advisory network. Please select another.',
  backBtn:              '← Back',
  nextLocationBtn:      'Next: Farm Details →',

  farmTitle:       'Your Farm',
  farmSubtitle:    'This helps us tailor soil and fertiliser advice.',
  soilLabel:       'Soil Type',
  cropLabel:       'Crop Variety',
  cropPlaceholder: 'e.g. Soybean JS-335',
  stageLabel:      'Growth Stage',
  errorSoil:       'Please select your soil type.',
  errorCrop:       'Please enter a crop variety (minimum 2 characters).',
  errorStage:      'Please select the growth stage.',
  submitBtn:       'Start Advising →',
  submittingBtn:   'Setting up…',

  soilClay:     { label: 'Clay',      desc: 'Heavy, water-retaining' },
  soilLoam:     { label: 'Loam',      desc: 'Balanced, fertile' },
  soilSandy:    { label: 'Sandy',     desc: 'Light, fast-draining' },
  soilClayLoam: { label: 'Clay Loam', desc: 'Moderately heavy' },
  soilSiltLoam: { label: 'Silt Loam', desc: 'Moisture-retaining' },

  stageSowing:     { label: 'Sowing',     desc: 'Seed planting' },
  stageVegetative: { label: 'Vegetative', desc: 'Leaf & stem growth' },
  stageFlowering:  { label: 'Flowering',  desc: 'Bloom & pollination' },
  stageMaturity:   { label: 'Maturity',   desc: 'Harvest ready' },

  greeting: 'Hello! I am CropCompass — your crop advisory assistant.\nAsk any question about your crop.',

  phaseGather:    'Looking up your profile and forecast…',
  phaseGenerate:  'Drafting your recommendation…',
  phaseVerify:    'Verifying advice against knowledge base…',
  phaseTranslate: 'Translating to your language…',

  toolGetProfile:    'Loading your profile…',
  toolFetchAdvisory: 'Checking weather forecast…',
  toolQueryKb:       'Searching crop knowledge base…',
  toolTranslate:     'Translating response…',

  micLabel:      'Speak your question',
  listenLabel:   'Listen',
  stopLabel:     'Stop',
  autoReadLabel: 'Auto-read answers',

  suggestions: [
    'When should I sow my crop?',
    'How much water does my crop need?',
    'What fertiliser should I apply now?',
    'What does the weather forecast say?',
  ],
}

export default eng_Latn
