
'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Radar, Search, ArrowRight, ArrowLeft,
  ChartNoAxesCombined, Lightbulb, Bookmark,
  Database, ExternalLink, Check, X, Copy,
  Info, Menu, Play,
} from 'lucide-react';

import { topics, trends as demoTrends, engagement } from '@/lib/mock-data';
import {
  searchTrends,
  getOpportunities,
  createOpportunity,
  updateOpportunityStatus,
} from '@/lib/api';

import type { Opportunity, Trend } from '@/types/trend';
import { analyzeVideos, type AIAnalysis, type AIVideo } from '@/lib/ai-api';

type Page = 'discover' | 'trends' | 'opportunities' | 'saved' | 'sources';
type Status = Opportunity['status'];

const tabs: { id: Page; label: string; icon: typeof Radar }[] = [
  { id: 'discover', label: 'Descubrir', icon: Radar },
  { id: 'trends', label: 'Tendencias', icon: ChartNoAxesCombined },
  { id: 'opportunities', label: 'Oportunidades', icon: Lightbulb },
  { id: 'saved', label: 'Guardados', icon: Bookmark },
  { id: 'sources', label: 'Fuentes', icon: Database },
];

const fmt = (value: number) =>
  new Intl.NumberFormat('es-CO', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value);

// Equivalencias para las sugerencias editoriales. No reemplazan una búsqueda real por hashtags.
const SEARCH_ALIASES: Record<string, string[]> = {
  aiagents: ['Agentes IA', 'agentes', 'AI Agents', 'IA'],
  automatizacion: ['automatización', 'automatizacion'],
  generativeai: ['Generative AI', 'IA generativa', 'generativa', 'IA'],
  fintech: ['FinTech', 'finanzas'],
  productividad: ['productividad'],
};

function getSearchTerms(input: string): string[] {
  const cleaned = input.trim().replace(/^#+/, '').trim();
  const key = cleaned
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[\s_-]/g, '');

  return [...new Set([cleaned, ...(SEARCH_ALIASES[key] || [])])];
}

export default function RadarApp() {
  const [page, setPage] = useState<Page>('discover');
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState('');
  const [platform, setPlatform] = useState('Todos');
  const [sort, setSort] = useState('Engagement');
  const [selected, setSelected] = useState<Trend | null>(null);

  const [apiTrends, setApiTrends] = useState<Trend[]>([]);
  const [saved, setSaved] = useState<Opportunity[]>([]);

  const [loading, setLoading] = useState(false);
  const [apiError, setApiError] = useState('');
  const [relatedSearch, setRelatedSearch] = useState('');
  const [savedError, setSavedError] = useState('');
  const [savingId, setSavingId] = useState<string | null>(null);
  const [toast, setToast] = useState('');
  const [aiAnalysis, setAiAnalysis] = useState<AIAnalysis | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState('');

  // Cargar oportunidades desde FastAPI al abrir la aplicación.
  useEffect(() => {
    let active = true;

    async function loadOpportunities() {
      try {
        const data = await getOpportunities();

        if (active) {
          setSaved(data);
          setSavedError('');
        }
      } catch (error) {
        console.error('Error al cargar oportunidades:', error);

        if (active) {
          setSavedError(
            'No fue posible cargar las oportunidades desde FastAPI.'
          );
        }
      }
    }

    void loadOpportunities();

    return () => {
      active = false;
    };
  }, []);

  const notify = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(''), 3000);
  };

  const openPage = (nextPage: Page) => {
    setPage(nextPage);
    setSelected(null);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const runSearch = async (value = query, selectedPlatform = platform) => {
    const term = value.trim();
    if (!term) return;

    setQuery(term);
    setSearch(term);
    setPlatform(selectedPlatform);
    setSelected(null);
    setPage('discover');
    setLoading(true);
    setApiError('');
    setRelatedSearch('');
    setApiTrends([]);

    window.scrollTo({ top: 0, behavior: 'smooth' });

    try {
      // El backend existente busca texto, no hashtags. Probamos el término
      // sin # y luego equivalencias conocidas cuando no hay coincidencias.
      const terms = getSearchTerms(term);
      const platformFilter = selectedPlatform === 'Todos' ? undefined : selectedPlatform;
      let matched: Trend[] = [];
      let matchedTerm = '';

      for (const candidate of terms) {
        const result = await searchTrends(candidate, platformFilter);
        if (result.length > 0) {
          matched = result;
          matchedTerm = candidate;
          break;
        }
      }

      setApiTrends(matched);
      if (matchedTerm && matchedTerm.toLocaleLowerCase() !== term.replace(/^#+/, '').toLocaleLowerCase()) {
        setRelatedSearch(matchedTerm);
      }
    } catch (error) {
      console.error('Error al consultar tendencias:', error);
      setApiError(
        'No fue posible consultar las tendencias. Verifica que FastAPI esté funcionando.'
      );
    } finally {
      setLoading(false);
    }
  };

  const results = useMemo(() => {
    const filtered = apiTrends.filter(
      (trend) => platform === 'Todos' || trend.platform === platform
    );

    if (sort === 'Vistas') {
      filtered.sort((a, b) => b.views - a.views);
    } else if (sort === 'Reciente') {
      filtered.sort((a, b) =>
        b.publishedAt.localeCompare(a.publishedAt)
      );
    } else {
      filtered.sort((a, b) => engagement(b) - engagement(a));
    }

    return filtered;
  }, [apiTrends, platform, sort]);

  const allVisibleTrends = apiTrends.length
    ? apiTrends
    : demoTrends;

  const openTrend = (trend: Trend) => {
    setSelected(trend);
    setPage('trends');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const getOpportunity = (trendId: string) =>
    saved.find((item) => item.trendId === trendId);

  const status = (trendId: string) =>
    getOpportunity(trendId)?.status;

  // Crear una oportunidad o actualizar su estado en FastAPI.
  const mark = async (trend: Trend, nextStatus: Status) => {
    if (savingId) return;

    setSavingId(trend.id);

    try {
      const existing = getOpportunity(trend.id);
      let updated: Opportunity;

      if (existing) {
        updated = await updateOpportunityStatus(
          existing.id,
          nextStatus
        );
      } else {
        const opportunity: Opportunity = {
          id: `opp-${trend.id}`,
          trendId: trend.id,
          status: nextStatus,
          savedAt: new Date().toISOString(),
        };

        updated = await createOpportunity(opportunity);
      }

      setSaved((current) => [
        ...current.filter((item) => item.trendId !== trend.id),
        updated,
      ]);

      setSavedError('');

      notify(
        nextStatus === 'Pendiente'
          ? 'Oportunidad guardada en FastAPI'
          : `Oportunidad ${nextStatus.toLowerCase()} en FastAPI`
      );
    } catch (error) {
      console.error('Error al guardar oportunidad:', error);
      notify('Error: no se pudo guardar en FastAPI');
    } finally {
      setSavingId(null);
    }
  };

  const removeSaved = async (item: Opportunity) => {
    // La API conocida no incluye DELETE.
    // Por seguridad, usamos Descartada en lugar de eliminar.
    if (savingId) return;

    setSavingId(item.trendId);

    try {
      const updated = await updateOpportunityStatus(
        item.id,
        'Descartada'
      );

      setSaved((current) =>
        current.map((entry) =>
          entry.id === item.id ? updated : entry
        )
      );

      notify('Oportunidad marcada como descartada');
    } catch (error) {
      console.error('Error al descartar:', error);
      notify('No se pudo actualizar la oportunidad');
    } finally {
      setSavingId(null);
    }
  };

  // Prueba aislada con 3 publicaciones ficticias. No representa recolección real.
  const runAiDemo = async () => {
    if (aiLoading) return;
    setAiLoading(true);
    setAiError('');
    setAiAnalysis(null);

    const capturedAt = new Date().toISOString();
    const demoVideos: AIVideo[] = [
      {
        id: 'yt:demo001',
        title: 'Automatizar reportes con inteligencia artificial',
        description: 'Tutorial ficticio de automatización de reportes para empresas.',
        author: 'Canal Demo IA',
        url: 'https://www.youtube.com/',
        published_at: '2026-10-10T18:00:00Z',
        metrics_collected_at: capturedAt,
        views: 12000,
        likes: 850,
        comments: 73,
      },
      {
        id: 'yt:demo002',
        title: 'Agentes de IA para pequeñas empresas',
        description: 'Ejemplos ficticios de agentes para equipos de trabajo.',
        author: 'Canal Demo Productividad',
        url: 'https://www.youtube.com/',
        published_at: '2026-10-11T15:00:00Z',
        metrics_collected_at: capturedAt,
        views: 25000,
        likes: 2100,
        comments: 180,
      },
      {
        id: 'yt:demo003',
        title: 'Herramientas de productividad con IA',
        description: 'Comparación ficticia de herramientas para mejorar procesos.',
        author: 'Canal Demo Tecnología',
        url: 'https://www.youtube.com/',
        published_at: '2026-10-12T12:00:00Z',
        metrics_collected_at: capturedAt,
        views: 8000,
        likes: 450,
        comments: 32,
      },
    ];

    try {
      const result = await analyzeVideos(
        '¿Qué videos destacan y qué contenido relevante podría producir 404 x ARCA-PROGRAM?',
        'Líderes y equipos de Latinoamérica',
        demoVideos
      );
      setAiAnalysis(result);
    } catch (error) {
      console.error('Error al consultar el agente de IA:', error);
      setAiError(
        'No se pudo conectar con la API de IA. Revisa la consola del navegador y verifica CORS o la disponibilidad del servicio.'
      );
    } finally {
      setAiLoading(false);
    }
  };

  const copyHook = (hook: string) => {
    void navigator.clipboard
      .writeText(hook)
      .then(() => notify('Hook copiado'))
      .catch(() => notify('No fue posible copiar el hook'));
  };

  const resultCard = (trend: Trend) => (
    <article className="result-card" key={trend.id}>
      <button
        className="result-image"
        onClick={() => openTrend(trend)}
        aria-label={`Analizar ${trend.title}`}
      >
        <img
          src={trend.image}
          alt="Imagen ilustrativa de la tendencia"
        />
        <span className="image-pill">
          <Play size={13} />
          {trend.platform}
        </span>
      </button>

      <div className="result-body">
        <div className="eyebrow">
          {trend.creator}
        </div>

        <h3>{trend.title}</h3>

        <div className="metrics">
          <div>
            <small>Vistas</small>
            <strong>{fmt(trend.views)}</strong>
          </div>
          <div>
            <small>Me gusta</small>
            <strong>{fmt(trend.likes)}</strong>
          </div>
          <div>
            <small>Engagement*</small>
            <strong className="lime">
              {engagement(trend).toFixed(1)}%
            </strong>
          </div>
        </div>

        <div className="result-actions">
          <span className="muted tiny">
            {trend.platform} · {trend.category}
          </span>

          <button
            className="primary small"
            onClick={() => openTrend(trend)}
          >
            Analizar <ArrowRight size={16} />
          </button>
        </div>
      </div>
    </article>
  );

  return (
    <div className="app-shell">
      <header className="topbar">
        <button
          className="brand"
          onClick={() => openPage('discover')}
        >
          <Radar size={25} color="var(--lime)" />
          <strong>404 x ARCA-PROGRAM</strong>
        </button>

        <span className="demo-label">
          INTELIGENCIA EDITORIAL
        </span>

        <button
          className="header-menu"
          aria-label="Ir a fuentes"
          onClick={() => openPage('sources')}
        >
          <Menu size={20} />
        </button>
      </header>

      <div className="desktop-layout">
        <aside className="sidebar">
          <div className="side-title">WORKSPACE</div>

          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={`side-link ${
                page === tab.id ? 'active' : ''
              }`}
              onClick={() => openPage(tab.id)}
            >
              <tab.icon size={19} />
              {tab.label}
            </button>
          ))}

          <div className="side-footer">
            404 x ARCA-PROGRAM · Inteligencia editorial
          </div>
        </aside>

        <main className="main">
          {page === 'discover' && (
            <div className="content">
              <section className="hero">
                <span className="kicker">
                  <span className="dot" />
                  INTELIGENCIA EDITORIAL LATAM
                </span>

                <h1>Descubre lo que viene.</h1>

                <p>
                  Encuentra las tendencias que importan.
                  Entiende por qué funcionan.
                  Transfórmalas en contenido.
                </p>

                <form
                  className="search-box"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void runSearch();
                  }}
                >
                  <Search size={20} />

                  <input
                    value={query}
                    onChange={(event) =>
                      setQuery(event.target.value)
                    }
                    placeholder="Busca un tema, hashtag o tendencia..."
                    aria-label="Buscar tendencia"
                  />

                  <button
                    className="search-go"
                    type="submit"
                    aria-label="Buscar"
                  >
                    <ArrowRight size={21} />
                  </button>
                </form>

                <div className="suggestions">
                  <span>SUGERENCIAS</span>

                  {[
                    '#AIAgents',
                    '#Automatización',
                    '#GenerativeAI',
                    '#FinTech',
                    '#Productividad',
                  ].map((suggestion) => (
                    <button
                      key={suggestion}
                      onClick={() =>
                        void runSearch(suggestion)
                      }
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </section>

              {!search ? (
                <>
                  <div className="section-heading">
                    <h2>Explora lo que está pasando</h2>
                    <span className="count">
                      4 colecciones
                    </span>
                  </div>

                  <div className="topic-grid">
                    {topics.map((topic) => (
                      <button
                        key={topic.title}
                        className="topic-card"
                        onClick={() =>
                          void runSearch(topic.query)
                        }
                      >
                        <div className="topic-image">
                          <img
                            src={topic.image}
                            alt="Imagen ilustrativa"
                          />
                          <span>{topic.tag}</span>
                        </div>

                        <div className="topic-body">
                          <h3>{topic.title}</h3>
                          <p>{topic.desc}</p>

                          <div className="topic-arrow">
                            Explorar colección
                            <ArrowRight size={16} />
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>

                  <div className="notice">
                    <Info size={16} />
                    Explora tendencias de contenido público
                    <span>
                      Explora · Analiza · Decide
                    </span>
                  </div>
                </>
              ) : (
                <>
                  <div className="result-heading">
                    <button
                      className="back"
                      onClick={() => {
                        setSearch('');
                        setQuery('');
                        setApiError('');
                      }}
                    >
                      <ArrowLeft size={16} />
                      Volver a inicio
                    </button>

                    <span className="demo-label">
                      RESULTADOS DE BÚSQUEDA
                    </span>
                  </div>

                  <h2 className="search-title">
                    Resultados para <span>{search}</span>
                  </h2>

                  {relatedSearch && !loading && !apiError && (
                    <div className="notice">
                      <Info size={16} />
                      Resultados relacionados con «{relatedSearch}».
                      La coincidencia con el hashtag puede ser aproximada.
                    </div>
                  )}

                  <div className="filters">
                    <div className="filter-group">
                      {[
                        'Todos',
                        'YouTube',
                        'TikTok',
                        'LinkedIn',
                      ].map((item) => (
                        <button
                          key={item}
                          className={
                            platform === item
                              ? 'selected'
                              : ''
                          }
                          onClick={() => void runSearch(search, item)}
                        >
                          {item}
                        </button>
                      ))}
                    </div>

                    <div className="filter-group">
                      {[
                        'Engagement',
                        'Vistas',
                        'Reciente',
                      ].map((item) => (
                        <button
                          key={item}
                          className={
                            sort === item
                              ? 'selected'
                              : ''
                          }
                          onClick={() =>
                            setSort(item)
                          }
                        >
                          {item}
                        </button>
                      ))}
                    </div>
                  </div>

                  {loading && (
                    <div className="empty" role="status">
                      <Search size={28} />
                      <h3>Buscando tendencias...</h3>
                      <p>
                        Consultando la información
                        disponible en 404 x ARCA-PROGRAM.
                      </p>
                    </div>
                  )}

                  {!loading && apiError && (
                    <div className="empty" role="alert">
                      <Info size={28} />
                      <h3>
                        No pudimos completar la búsqueda
                      </h3>
                      <p>{apiError}</p>
                    </div>
                  )}

                  {!loading && !apiError && (
                    <>
                      <div className="results-grid">
                        {results.map(resultCard)}
                      </div>

                      {results.length === 0 && (
                        <div className="empty">
                          <Search size={28} />
                          <h3>No encontramos resultados</h3>
                          <p>
                            Prueba otra búsqueda o
                            selecciona «Todos» en los filtros.
                          </p>
                        </div>
                      )}
                    </>
                  )}
                </>
              )}
            </div>
          )}

          {page === 'trends' && (
            <div className="content">
              {selected ? (
                <>
                  <button
                    className="back"
                    onClick={() => openPage('discover')}
                  >
                    <ArrowLeft size={16} />
                    Volver a descubrir
                  </button>

                  <div className="page-head">
                    <span className="kicker">
                      ANÁLISIS DE TENDENCIA
                    </span>
                    <h1>{selected.title}</h1>
                    <p>
                      {selected.creator} ·{' '}
                      {selected.platform} ·{' '}
                      {selected.publishedAt}
                    </p>
                  </div>

                  <div className="detail-grid">
                    <div>
                      <div className="detail-cover">
                        <img
                          src={selected.image}
                          alt="Imagen ilustrativa"
                        />
                      </div>

                      <div className="metric-grid">
                        {[
                          {
                            label: 'Vistas',
                            value: fmt(selected.views),
                          },
                          {
                            label: 'Me gusta',
                            value: fmt(selected.likes),
                          },
                          {
                            label: 'Comentarios',
                            value: fmt(selected.comments),
                          },
                          {
                            label: 'Engagement*',
                            value: `${engagement(
                              selected
                            ).toFixed(2)}%`,
                          },
                        ].map((metric) => (
                          <div
                            className="metric-tile"
                            key={metric.label}
                          >
                            <small>{metric.label}</small>
                            <strong>{metric.value}</strong>
                          </div>
                        ))}
                      </div>

                      <div className="notice">
                        <Info size={16} />
                        Sin mediciones históricas:
                        no es posible calcular velocidad
                        ni crecimiento.
                      </div>
                    </div>

                    <div className="analysis-panel">
                      <span className="kicker">
                        INTERPRETACIÓN EDITORIAL
                      </span>

                      <h2>¿Por qué podría funcionar?</h2>
                      <p>{selected.insight}</p>
                      <hr />

                      <small>AUDIENCIA RELEVANTE</small>
                      <p>{selected.audience}</p>

                      <small>ÁNGULO PROPUESTO</small>
                      <p>{selected.angle}</p>

                      <small>FORMATO</small>
                      <p>{selected.format}</p>

                      <div className="hook">
                        <small>HOOK SUGERIDO</small>
                        <p>“{selected.hook}”</p>

                        <button
                          onClick={() =>
                            copyHook(selected.hook)
                          }
                        >
                          <Copy size={14} />
                          Copiar
                        </button>
                      </div>

                      {selected.sourceUrl && (
                        <a
                          href={selected.sourceUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          Ver publicación de origen
                          <ExternalLink size={14} />
                        </a>
                      )}

                      <button
                        className="primary full"
                        disabled={savingId !== null}
                        onClick={() =>
                          void mark(selected, 'Pendiente')
                        }
                      >
                        <Bookmark size={17} />
                        {savingId === selected.id
                          ? 'Guardando...'
                          : status(selected.id)
                            ? 'Actualizar oportunidad'
                            : 'Guardar oportunidad'}
                      </button>
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div className="page-head">
                    <span className="kicker">
                      ANÁLISIS EDITORIAL
                    </span>
                    <h1>Tendencias</h1>
                    <p>
                      Selecciona una publicación para
                      examinar sus métricas y su
                      interpretación editorial.
                    </p>
                  </div>

                  <div className="results-grid">
                    {allVisibleTrends.map(resultCard)}
                  </div>
                </>
              )}
            </div>
          )}

          {page === 'opportunities' && (
            <div className="content">
              <div className="page-head">
                <span className="kicker">
                  MOTOR EDITORIAL · ARCA-PROGRAM
                </span>
                <h1>Oportunidades editoriales</h1>
                <p>
                  Revisa las propuestas y registra
                  tus decisiones en FastAPI.
                </p>
              </div>

              <section className="analysis-panel" aria-label="Análisis editorial con IA">
                <span className="kicker">INTELIGENCIA EDITORIAL · IA</span>
                <h2>Análisis editorial con IA</h2>
                <p>
                  Obtén un ranking, hallazgos y recomendaciones editoriales
                  a partir de publicaciones seleccionadas.
                </p>
                <button
                  className="primary"
                  type="button"
                  disabled={aiLoading}
                  onClick={() => void runAiDemo()}
                >
                  {aiLoading ? 'Analizando videos...' : 'Analizar con IA'}
                </button>

                <p className="muted tiny">
                  Por ahora se utilizan tres videos de prueba precargados;
                  el análisis aún no toma los filtros de la búsqueda.
                </p>

                {aiError && (
                  <div className="notice" role="alert">
                    <Info size={16} />
                    {aiError}
                  </div>
                )}

                {aiAnalysis && (
                  <div aria-live="polite">
                    <h3>Resumen del agente</h3>
                    <p>{aiAnalysis.summary || 'Sin resumen disponible.'}</p>
                    <small>Modo: {aiAnalysis.analysis_mode}</small>

                    <h3>Ranking de videos</h3>
                    {aiAnalysis.ranking.length === 0 ? (
                      <p>No hay videos clasificados.</p>
                    ) : (
                      <ol>
                        {aiAnalysis.ranking.map((item) => (
                          <li key={`${item.video_id}-${item.position}`}>
                            {item.video_id} · {fmt(item.value)} {item.metric === 'views' ? 'vistas' : item.metric}
                          </li>
                        ))}
                      </ol>
                    )}

                    <h3>Hallazgos</h3>
                    {aiAnalysis.findings.length === 0 ? (
                      <p>El agente no devolvió hallazgos.</p>
                    ) : (
                      <div className="opportunities-grid">
                        {aiAnalysis.findings.map((finding, index) => (
                          <article className="opportunity" key={`finding-${index}`}>
                            <h3>{finding.observation}</h3>
                            <p>{finding.hypothesis}</p>
                            <small>Fuentes: {finding.source_video_ids.join(', ') || 'Sin fuentes'}</small>
                          </article>
                        ))}
                      </div>
                    )}

                    <h3>Recomendaciones de IA</h3>
                    {aiAnalysis.recommendations.length === 0 ? (
                      <p>El agente no devolvió recomendaciones.</p>
                    ) : (
                      <div className="opportunities-grid">
                        {aiAnalysis.recommendations.map((recommendation, index) => (
                          <article className="opportunity" key={`recommendation-${index}`}>
                            <span className="kicker">RECOMENDACIÓN GENERADA POR IA</span>
                            <h2>{recommendation.title}</h2>
                            <small>FORMATO SUGERIDO</small>
                            <p>{recommendation.suggested_format}</p>
                            <small>JUSTIFICACIÓN</small>
                            <p>{recommendation.reason}</p>
                            <small>Videos: {recommendation.source_video_ids.join(', ') || 'Sin fuentes'}</small>
                          </article>
                        ))}
                      </div>
                    )}

                    <h3>Limitaciones del análisis</h3>
                    {aiAnalysis.limitations.length === 0 ? (
                      <p>No se reportaron limitaciones.</p>
                    ) : (
                      <ul>
                        {aiAnalysis.limitations.map((limitation, index) => (
                          <li key={`limitation-${index}`}>{limitation}</li>
                        ))}
                      </ul>
                    )}
                    <p className="muted tiny">
                      Resultados generados a partir de tres registros de prueba.
                      Las recomendaciones de IA todavía no se guardan como oportunidades.
                    </p>
                  </div>
                )}
              </section>

              <div className="opportunities-grid">
                {allVisibleTrends.map((trend) => (
                  <article
                    className="opportunity"
                    key={trend.id}
                  >
                    <span className="kicker">
                      PROPUESTA ·{' '}
                      {status(trend.id) || 'PENDIENTE'}
                    </span>

                    <h2>
                      {trend.category}: {trend.angle}
                    </h2>

                    <div className="op-meta">
                      {trend.platform} ·{' '}
                      {fmt(trend.views)} vistas
                    </div>

                    <small>FIT DE AUDIENCIA</small>
                    <p>{trend.audience}</p>

                    <small>FORMATO RECOMENDADO</small>
                    <p>{trend.format}</p>

                    <div className="hook">
                      <small>HOOK DE APERTURA</small>
                      <p>“{trend.hook}”</p>
                      <button
                        onClick={() =>
                          copyHook(trend.hook)
                        }
                      >
                        <Copy size={14} />
                        Copiar
                      </button>
                    </div>

                    <div className="op-actions">
                      <button
                        className="primary"
                        disabled={savingId !== null}
                        onClick={() =>
                          void mark(trend, 'Aprobada')
                        }
                      >
                        <Check size={16} />
                        Aprobar
                      </button>

                      <button
                        className="secondary"
                        disabled={savingId !== null}
                        onClick={() =>
                          void mark(trend, 'Pendiente')
                        }
                      >
                        <Bookmark size={16} />
                        Guardar
                      </button>

                      <button
                        className="secondary danger"
                        disabled={savingId !== null}
                        onClick={() =>
                          void mark(trend, 'Descartada')
                        }
                      >
                        <X size={16} />
                        Descartar
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          )}

          {page === 'saved' && (
            <div className="content">
              <div className="page-head">
                <span className="kicker">
                  PIPELINE EDITORIAL
                </span>
                <h1>Ideas guardadas</h1>
                <p>
                  Oportunidades registradas en FastAPI.
                </p>
              </div>

              {savedError && (
                <div className="notice" role="alert">
                  <Info size={16} />
                  {savedError}
                </div>
              )}

              {saved.length === 0 ? (
                <div className="empty">
                  <Bookmark size={28} />
                  <h3>
                    No hay oportunidades cargadas
                  </h3>
                  <p>
                    Explora tendencias y guarda una
                    propuesta para verla aquí.
                  </p>
                  <button
                    className="primary"
                    onClick={() =>
                      openPage('discover')
                    }
                  >
                    Descubrir contenido
                  </button>
                </div>
              ) : (
                <div className="saved-grid">
                  {saved.map((item) => {
                    const trend = allVisibleTrends.find(
                      (entry) =>
                        entry.id === item.trendId
                    );

                    return (
                      <article
                        className="saved-card"
                        key={item.id}
                      >
                        <span className="kicker">
                          {item.status}
                        </span>

                        <h3>
                          {trend?.angle ||
                            `Tendencia ${item.trendId}`}
                        </h3>

                        <p>
                          {trend
                            ? `${trend.category} · ${trend.format}`
                            : 'Busca esta tendencia para recuperar su análisis.'}
                        </p>

                        <div className="op-actions">
                          {trend && (
                            <button
                              className="secondary"
                              onClick={() =>
                                openTrend(trend)
                              }
                            >
                              Ver análisis
                            </button>
                          )}

                          {item.status !== 'Descartada' && (
                            <button
                              className="secondary danger"
                              disabled={savingId !== null}
                              onClick={() =>
                                void removeSaved(item)
                              }
                            >
                              Descartar
                            </button>
                          )}
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {page === 'sources' && (
            <div className="content">
              <div className="page-head">
                <span className="kicker">
                  TRANSPARENCIA DE DATOS
                </span>
                <h1>Fuentes y estado</h1>
                <p>
                  Consulta la procedencia de los datos y el estado de las conexiones.
                </p>
              </div>

              <div className="sources-grid">
                <article className="source-card">
                  <h2>FastAPI · Tendencias</h2>
                  <span className="status-wait">
                    INTEGRADO EN FRONTEND
                  </span>
                  <p>
                    El buscador consulta /api/trends.
                    La procedencia y verificación de los registros depende
                    de la fuente cargada en el backend.
                  </p>
                </article>

                <article className="source-card">
                  <h2>FastAPI · Oportunidades</h2>
                  <span className="status-wait">
                    INTEGRADO EN FRONTEND
                  </span>
                  <p>
                    GET, POST y PATCH permiten consultar,
                    crear y actualizar decisiones editoriales.
                  </p>
                </article>

                <article className="source-card">
                  <h2>YouTube, TikTok y LinkedIn</h2>
                  <span className="status-wait">
                    RECOLECCIÓN POR VERIFICAR
                  </span>
                  <p>
                    Falta confirmar la obtención directa
                    de publicaciones reales.
                  </p>
                </article>

                <article className="source-card">
                  <h2>Análisis de IA e históricos</h2>
                  <span className="status-wait">
                    POR VERIFICAR
                  </span>
                  <p>
                    El crecimiento requiere mediciones
                    de las mismas publicaciones en
                    distintos momentos.
                  </p>
                </article>
              </div>

              <div className="notice">
                <Info size={16} />
                Las métricas procedentes de registros precargados no representan
                tendencias verificadas. El análisis de IA utiliza videos de prueba.
              </div>
            </div>
          )}
        </main>
      </div>

      <nav
        className="bottom-nav"
        aria-label="Navegación principal"
      >
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => openPage(tab.id)}
            className={
              page === tab.id ? 'active' : ''
            }
          >
            <tab.icon size={21} />
            <span>{tab.label}</span>
          </button>
        ))}
      </nav>

      {toast && (
        <div role="status" className="toast">
          <Check size={17} />
          {toast}
        </div>
      )}
    </div>
  );
}
