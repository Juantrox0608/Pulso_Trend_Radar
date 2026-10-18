
import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';

const AI_API_URL = 'https://radar-ai-8xi7.onrender.com';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const response = await fetch(`${AI_API_URL}/analyze`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify(body),
      cache: 'no-store',
      signal: AbortSignal.timeout(120000),
    });

    const result = await response.json();

    return NextResponse.json(result, {
      status: response.status,
    });
  } catch (error) {
    console.error('Error al conectar con IA:', error);

    return NextResponse.json(
      {
        error: {
          message: 'No fue posible conectar con el microservicio de IA.',
        },
      },
      { status: 502 }
    );
  }
}
