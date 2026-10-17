import type {Trend} from '@/types/trend';
const API_URL=process.env.NEXT_PUBLIC_API_URL;
export async function searchTrends(query:string):Promise<Trend[]> {
 if(!API_URL) throw new Error('NEXT_PUBLIC_API_URL no configurada');
 const response=await fetch(`${API_URL}/api/trends?query=${encodeURIComponent(query)}`,{cache:'no-store'});
 if(!response.ok) throw new Error(`Error API ${response.status}`);
 return response.json() as Promise<Trend[]>;
}
