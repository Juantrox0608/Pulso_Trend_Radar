
import type { Opportunity, Trend } from '@/types/trend';

const API_URL = process.env.NEXT_PUBLIC_API_URL;

function getApiUrl(): string {
  if (!API_URL) {
    throw new Error('NEXT_PUBLIC_API_URL no configurada');
  }

  return API_URL.replace(/\/$/, '');
}

// CONTRATOS DEL BACKEND PRINCIPAL

type ResearchSource = {
  id: string;
  title: string | null;
  url: string;
  platform: 'youtube' | 'tiktok' | 'linkedin';
};

type ResearchMetric = {
  id: string;
  platform: string;
  views: number | null;
  likes: number | null;
  comments: number | null;
  shares: number | null;
  metrics_collected_at: string;
};

type ResearchRecommendation = {
  title: string;
  suggested_format: string;
  reason: string;
  source_video_ids: string[];
};

type ResearchResponse = {
  analysis: {
    summary: string;
    recommendations: ResearchRecommendation[];
    limitations: string[];
  };
  sources: ResearchSource[];
  metrics: ResearchMetric[];
  collection: {
    mode: string;
    simulated: boolean;
  };
};

// BÚSQUEDA REAL + RECOLECCIÓN + IA

export async function searchTrends(
  query: string,
  platform?: string,
  _category?: string
): Promise<Trend[]> {
  const topic = query.trim();

  if (!topic) {
    return [];
  }

  // El backend admite una plataforma por investigación.
  // YouTube es la plataforma inicial cuando se elige "Todos".
  const platforms: Record<string, 'youtube' | 'tiktok' | 'linkedin'> = {
    YouTube: 'youtube',
    TikTok: 'tiktok',
    LinkedIn: 'linkedin',
  };

  const selectedPlatform = platform
    ? platforms[platform] || 'youtube'
    : 'youtube';

  const response = await fetch('/api/ai/analyze', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    cache: 'no-store',
    body: JSON.stringify({
      question:
        `Analiza las publicaciones sobre "${topic}". ` +
        'Identifica los patrones observables, distingue las hipótesis ' +
        'de los hechos y propone oportunidades editoriales para PULSO.',
      audience:
        'Líderes, emprendedores, profesionales y equipos de Latinoamérica',
      filters: {
        query: topic,
        platform: selectedPlatform,
        country: 'CO',
        sample_size: 5,
      },
    }),
  });

  let data: ResearchResponse & {
    error?: { message?: string; code?: string };
  };

  try {
    data = await response.json();
  } catch {
    throw new Error(
      'El backend no devolvió una respuesta JSON válida.'
    );
  }

  if (!response.ok) {
    throw new Error(
      data.error?.message ||
      `No se pudo completar la investigación (${response.status}).`
    );
  }

  if (!data.sources || !Array.isArray(data.sources)) {
    throw new Error(
      'El backend no devolvió publicaciones con el formato esperado.'
    );
  }

  const metricsById = new Map<string, ResearchMetric>(
    (data.metrics || []).map((metric) => [metric.id, metric])
  );

  const platformNames: Record<string, Trend['platform']> = {
    youtube: 'YouTube',
    tiktok: 'TikTok',
    linkedin: 'LinkedIn',
  };

  const recommendations = data.analysis?.recommendations || [];

  return data.sources.map((source): Trend => {
    const metrics = metricsById.get(source.id);

    const recommendation = recommendations.find(
      (item) => item.source_video_ids.includes(source.id)
    );

    return {
      id: source.id,

      title: source.title || 'Publicación sin título',

      creator: 'Autor no disponible',

      platform: platformNames[source.platform],

      category: topic,

      // El tipo Trend exige números. Los datos desconocidos
      // se representan temporalmente como cero en la interfaz.
      views: metrics?.views ?? 0,

      likes: metrics?.likes ?? 0,

      comments: metrics?.comments ?? 0,

      // El endpoint /research no incluye fecha de publicación.
      publishedAt: '',

      // Imagen ilustrativa, no miniatura del contenido.
      image: '/favicon.ico',

      insight:
        data.analysis?.summary ||
        'Sin análisis editorial disponible.',

      angle:
        recommendation?.title ||
        'Oportunidad pendiente de identificar',

      hook:
        recommendation?.reason ||
        'No se generó una propuesta específica.',

      audience:
        'Profesionales y equipos de Latinoamérica',

      format:
        recommendation?.suggested_format ||
        'Formato por definir',

      sourceUrl: source.url,
    };
  });
}

// CONSULTAR OPORTUNIDADES GUARDADAS

export async function getOpportunities(): Promise<Opportunity[]> {
  const response = await fetch(
    `${getApiUrl()}/api/opportunities`,
    {
      cache: 'no-store',
    }
  );

  if (!response.ok) {
    throw new Error(
      `Error al consultar oportunidades: ${response.status}`
    );
  }

  return response.json() as Promise<Opportunity[]>;
}

// CREAR O GUARDAR OPORTUNIDAD

export async function createOpportunity(
  opportunity: Opportunity
): Promise<Opportunity> {
  const response = await fetch(
    `${getApiUrl()}/api/opportunities`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(opportunity),
    }
  );

  if (!response.ok) {
    throw new Error(
      `Error al guardar oportunidad: ${response.status}`
    );
  }

  return response.json() as Promise<Opportunity>;
}

// ACTUALIZAR ESTADO DE OPORTUNIDAD

export async function updateOpportunityStatus(
  opportunityId: string,
  status: Opportunity['status']
): Promise<Opportunity> {
  const response = await fetch(
    `${getApiUrl()}/api/opportunities/${encodeURIComponent(opportunityId)}`,
    {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ status }),
    }
  );

  if (!response.ok) {
    throw new Error(
      `Error al actualizar oportunidad: ${response.status}`
    );
  }

  return response.json() as Promise<Opportunity>;
}
