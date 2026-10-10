/** Lowercase and strip Vietnamese diacritics so 'sac' matches 'Sạc'. */
export function normalize(text: string): string {
  return text.toLowerCase().replace(/đ/g, 'd').normalize('NFD').replace(/\p{Mn}/gu, '');
}
