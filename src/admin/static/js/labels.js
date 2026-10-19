/** O'zbekcha nomlar: korpus kategoriyalari (bir joyda — barcha sahifalar shu yerdan oladi). */
export const CATEGORY_LABELS = {
  general: 'Umumiy',
  disability_rights: 'Nogironlik huquqlari',
  pensions_and_benefits: 'Nafaqalar va pensiyalar',
  labor_rights: 'Mehnat huquqlari',
  labor_code: 'Mehnat kodeksi',
  medical_social_expertise: 'Tibbiy-ijtimoiy ekspertiza (TIEK)',
  tax_benefits: 'Soliq imtiyozlari',
  rehabilitation_prosthetics: 'Protez-ortopediya va reabilitatsiya',
  sanatorium_health: 'Sanatoriy-kurortda davolanish',
  healthcare: 'Sog‘liqni saqlash',
  inclusive_education: 'Inklyuziv ta’lim',
  education: 'Ta’lim',
  accessibility_infrastructure: 'To‘siqsiz muhit',
  transport_benefits: 'Transport imtiyozlari',
  housing_rights: 'Uy-joy huquqlari',
  social_services: 'Ijtimoiy xizmatlar',
  social_protection: 'Ijtimoiy himoya',
  social_protection_governance: 'Ijtimoiy himoya boshqaruvi',
  legal_protection: 'Huquqiy himoya',
  international_treaty: 'Xalqaro shartnomalar (BMT Konvensiyasi)',
};

export function categoryLabel(key) {
  if (!key) return 'Umumiy';
  return CATEGORY_LABELS[key] || 'Boshqa';
}
