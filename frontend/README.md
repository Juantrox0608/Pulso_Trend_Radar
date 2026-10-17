# 30X RADAR — Frontend Next.js

Prototipo funcional de UX inspirado en los archivos HTML exportados desde Stitch. **Todos los datos son simulados**; no hay conexión real con YouTube, TikTok ni IA.

## Requisitos
- Node.js 20 o superior
- npm

## Ejecutar
```bash
npm install
npm run dev
```
Abrir http://localhost:3000

## Publicar en GitHub
Crear un repositorio vacío `30x-radar-frontend`, abrir una terminal dentro de esta carpeta y ejecutar:
```bash
git init
git add .
git commit -m "feat: initial 30X Radar Next.js prototype"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/30x-radar-frontend.git
git push -u origin main
```
Reemplazar `TU_USUARIO` con tu usuario de GitHub.

## Arquitectura
- `src/components/RadarApp.tsx`: experiencia interactiva de cinco vistas
- `src/lib/mock-data.ts`: datos simulados de tendencias
- `src/lib/api.ts`: cliente preparado para FastAPI, todavía sin usar
- `src/types/trend.ts`: contratos TypeScript
- `src/app/globals.css`: sistema visual responsive basado en Stitch
- `public/reference/`: HTML exportado de Stitch, guardado como referencia; no es código de producción

## Próximas integraciones
1. Acordar con backend respuesta `GET /api/trends?query=...`.
2. Configurar `.env.local` con `NEXT_PUBLIC_API_URL` (solo URL pública, nunca secretos).
3. Sustituir mock data por respuestas validadas del backend.
4. Persistir guardados en servidor (por ahora localStorage).
5. Añadir estados de carga, error y cobertura parcial al cliente API.

## Notas
- Las imágenes originales exportadas desde Stitch son URLs remotas que podrían dejar de funcionar; sustituir por assets propios antes de producción.
- Engagement demo = (likes + comentarios) / vistas × 100. No se inventa crecimiento sin mediciones históricas.
- TikTok requiere revisar permisos y términos antes de conectar búsquedas reales.
