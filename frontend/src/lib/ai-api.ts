
export interface AIVideo {
  id: string;
  title: string;
  description: string;
  author: string;
  url: string;
  published_at: string;
  metrics_collected_at: string;
  views: number;
  likes: number;
  comments: number;
}

export interface AIAnalysis {
  summary: string;
  findings: {
    observation: string;
    hypothesis: string;
    source_video_ids: string[];
  }[];
  recommendations: {
    title: string;
    suggested_format: string;
    reason: string;
    source_video_ids: string[];
  }[];
  limitations: string[];
  ranking: {
    video_id: string;
    position: number;
    metric: string;
    value: number;
  }[];
  ranking_method: string;
  unranked_video_ids: string[];
  analysis_mode: string;
}

export async function analyzeVideos(
  question: string,
  audience: string,
  videos: AIVideo[]
): Promise<AIAnalysis> {
  const response = await fetch('/api/ai/analyze', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      question,
      audience,
      videos,
    }),
  });

  if (!response.ok) {
    let message = `Error API ${response.status}`;

    try {
      const details = await response.json();
      message =
        details?.error?.message ||
        (typeof details?.error === 'string'
          ? details.error
          : message);
    } catch {
      // Mantener el mensaje HTTP original
    }

    throw new Error(message);
  }

  return response.json() as Promise<AIAnalysis>;
}
