
import type { Trend } from '@/types/trend';

const aliases: Record<string, string[]> = {
  'Agentes IA': [
    'agentes ia', 'agentes de ia', 'agentes autonomos',
    'ai agents', 'aiagents', 'inteligencia artificial',
    'artificial intelligence'
  ],
  'Automatización': [
    'automatizacion', 'automation', 'automatizacion empresarial',
    'automatizacion de negocios', 'procesos automatizados'
  ],
  'IA generativa': [
    'ia generativa', 'generative ai', 'generativeai',
    'genai', 'modelos de ia', 'inteligencia artificial'
  ],
  'Productividad': [
    'productividad', 'productivity', 'herramientas de productividad',
    'software para equipos'
  ]
};

function normalize(value: string): string {
  return value
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/#/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

export function matchesTrend(trend: Trend, query: string): boolean {
  const q = normalize(query);
  if (!q) return true;

  const searchable = normalize([
    trend.title,
    trend.category,
    trend.creator,
    trend.insight
  ].join(' '));

  if (searchable.includes(q)) return true;

  const categoryAliases = aliases[trend.category] ?? [];

  return categoryAliases.some(alias => {
    const normalizedAlias = normalize(alias);
    return normalizedAlias === q ||
      (q.length >= 4 && normalizedAlias.includes(q));
  });
}
