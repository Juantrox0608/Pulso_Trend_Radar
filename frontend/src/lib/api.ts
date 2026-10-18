
import type { Opportunity, Trend } from '@/types/trend';

const API_URL = process.env.NEXT_PUBLIC_API_URL;

function getApiUrl(): string {
  if (!API_URL) {
    throw new Error('NEXT_PUBLIC_API_URL no configurada');
  }

  return API_URL;
}

// Buscar tendencias con filtros opcionales
export async function searchTrends(
  query: string,
  platform?: string,
  category?: string
): Promise<Trend[]> {
  const params = new URLSearchParams();

  if (query.trim()) {
    params.set('query', query.trim());
  }

  if (platform && platform !== 'All') {
    params.set('platform', platform);
  }

  if (category && category !== 'All') {
    params.set('category', category);
  }

  const url = `${getApiUrl()}/api/trends?${params.toString()}`;

  const response = await fetch(url, {
    cache: 'no-store',
  });

  if (!response.ok) {
    throw new Error(`Error API ${response.status}`);
  }

  return response.json() as Promise<Trend[]>;
}

// Consultar oportunidades guardadas
export async function getOpportunities(): Promise<Opportunity[]> {
  const response = await fetch(
    `${getApiUrl()}/api/opportunities`,
    { cache: 'no-store' }
  );

  if (!response.ok) {
    throw new Error(`Error API ${response.status}`);
  }

  return response.json() as Promise<Opportunity[]>;
}

// Crear o guardar una oportunidad
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
    throw new Error(`Error API ${response.status}`);
  }

  return response.json() as Promise<Opportunity>;
}

// Cambiar el estado de una oportunidad
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
    throw new Error(`Error API ${response.status}`);
  }

  return response.json() as Promise<Opportunity>;
}
