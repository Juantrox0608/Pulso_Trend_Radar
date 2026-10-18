
export type Platform = 'YouTube' | 'TikTok' | 'LinkedIn';

export type Trend = {
  id: string;
  title: string;
  creator: string;
  platform: Platform;
  category: string;
  views: number;
  likes: number;
  comments: number;
  publishedAt: string;
  image: string;
  insight: string;
  angle: string;
  hook: string;
  audience: string;
  format: string;
  sourceUrl?: string;
};

export type Opportunity = {
  id: string;
  trendId: string;
  status: 'Pendiente' | 'Aprobada' | 'Descartada';
  savedAt: string;
};
