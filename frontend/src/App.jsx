import { useEffect, useMemo, useRef, useState } from "react";
import { translate, translateError } from "./i18n.js";

const LEGAL_NOTICE =
  "Use apenas para conteúdos próprios, de domínio público ou com autorização do autor. O usuário é responsável por respeitar os direitos autorais e os Termos de Serviço de cada plataforma.";
const HISTORY_KEY = "saveclip.history";
const THEME_KEY = "saveclip.theme";
const LANGUAGE_KEY = "saveclip.language";
const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

function isAgeRestrictionError(message) {
  return /restri.{0,30}idade|idade.{0,30}restri|age[- ]restricted/i.test(message || "");
}

async function request(path, body) {
  let response;
  try {
    response = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error("Não foi possível conectar ao SaveClip. Verifique se o serviço está ativo.");
  }
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = result.detail || result.error || "Não foi possível concluir a solicitação.";
    throw new Error(typeof message === "string" ? message : "O pedido não foi aceito.");
  }
  return result;
}

function prettyDuration(seconds, language) {
  if (!Number.isFinite(Number(seconds))) return translate("Duração indisponível", language);
  const total = Math.floor(Number(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
    : `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function prettySize(bytes) {
  const value = Number(bytes);
  if (!value) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}

function Icon({ name, size = 18 }) {
  const paths = {
    clip: <><path d="M8 8.5v7a4 4 0 0 0 8 0V7.25a3.25 3.25 0 0 0-6.5 0V15.5a1.75 1.75 0 0 0 3.5 0V9" /><path d="M5 5.5v13" /></>,
    brand: <><path d="M8 3.75h8a2 2 0 0 1 2 2V20l-6-3.5L6 20V5.75a2 2 0 0 1 2-2Z" fill="currentColor" stroke="none" /><path d="m10 8.5 5 3-5 3z" fill="#fff" stroke="none" /></>,
    add: <path d="M12 5v14M5 12h14" />,
    settings: <><circle cx="12" cy="12" r="3" /><path d="m19.4 15 .1.1 1.4 1.1-1.4 2.4-1.7-.7a8 8 0 0 1-1.5.9l-.3 1.8h-2.8l-.3-1.8a8 8 0 0 1-1.5-.9l-1.7.7-1.4-2.4 1.4-1.1A8 8 0 0 1 7.5 13l-1.8-.3V9.9l1.8-.3a8 8 0 0 1 .8-1.5L6.9 6.7l1.4-2.4 1.7.7a8 8 0 0 1 1.5-.9l.3-1.8h2.8l.3 1.8a8 8 0 0 1 1.5.9l1.7-.7 1.4 2.4-1.4 1.1a8 8 0 0 1 .8 1.5l1.8.3v2.8l-1.8.3a8 8 0 0 1-.7 2.3Z" /></>,
    clipboard: <><rect x="8" y="7" width="12" height="14" rx="2" /><path d="M16 7V5a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h2" /></>,
    trash: <><path d="M3 6h18M8 6V4h8v2m3 0-1 14H6L5 6" /><path d="M10 11v5m4-5v5" /></>,
    download: <><path d="M12 3v12m-5-5 5 5 5-5" /><path d="M5 17v3h14v-3" /></>,
    video: <><rect x="3" y="5" width="13" height="14" rx="2" /><path d="m16 10 5-3v10l-5-3z" /></>,
    history: <><path d="M3 12a9 9 0 1 0 2.6-6.4L3 8" /><path d="M3 3v5h5m4-1v5l3 2" /></>,
    arrow: <><path d="M12 19V5m-6 6 6-6 6 6" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    folder: <><path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M3 9h18" /></>,
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}

function App() {
  const [language, setLanguage] = useState(() =>
    localStorage.getItem(LANGUAGE_KEY) === "en" ? "en" : "pt-BR",
  );
  const t = (text) => translate(text, language);
  const trError = (message) => translateError(message, language);
  const [startupSettingsLoaded, setStartupSettingsLoaded] = useState(false);
  const [startupSettingsError, setStartupSettingsError] = useState("");
  const [url, setUrl] = useState("");
  const [info, setInfo] = useState(null);
  const [formatId, setFormatId] = useState("");
  const [mediaType, setMediaType] = useState("video");
  const [previewError, setPreviewError] = useState("");
  const [volumePercent, setVolumePercent] = useState(100);
  const [outputName, setOutputName] = useState("");
  const [selectedItems, setSelectedItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [job, setJob] = useState(null);
  const [history, setHistory] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    } catch {
      return [];
    }
  });
  const [theme, setTheme] = useState(() => localStorage.getItem(THEME_KEY) || "dark");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsError, setSettingsError] = useState("");
  const [downloadDir, setDownloadDir] = useState("");
  const [defaultDownloadDir, setDefaultDownloadDir] = useState("");
  const [outputTemplate, setOutputTemplate] = useState("{title} - {id}");
  const [savingOutputTemplate, setSavingOutputTemplate] = useState(false);
  const [canChangeDownloadDir, setCanChangeDownloadDir] = useState(false);
  const [savingDownloadDir, setSavingDownloadDir] = useState(false);
  const [view, setView] = useState("queue");
  const eventSource = useRef(null);
  const urlInput = useRef(null);

  const formats = info?.formats || [];
  const videoFormats = useMemo(() => formats.filter((format) => format.type === "video"), [formats]);
  const audioFormats = useMemo(() => formats.filter((format) => format.type === "audio"), [formats]);
  const availableFormats = mediaType === "audio" ? audioFormats : videoFormats;
  const previewUrl = info?.preview?.[mediaType];
  const previewUnavailable = !previewUrl || previewError === mediaType;
  const formatAvailable = availableFormats.some((format) => format.format_id === formatId);
  const isPlaylist = Boolean(info?.is_playlist && info?.items?.length);
  const downloadActive = job && !TERMINAL_STATUSES.has(job.status);
  const statusLabel = busy
    ? t("Analisando o link…")
    : job?.status === "downloading"
      ? t("Baixando seu conteúdo…")
      : job?.status === "processing"
        ? t("Preparando arquivo…")
        : job?.status === "cancel_requested"
          ? t("Cancelando download…")
          : job?.status === "cancelled"
            ? t("Download cancelado")
            : job?.status === "failed"
          ? t("Download interrompido")
          : job?.status === "completed"
            ? t("Download concluído")
            : job?.status === "analyzing"
              ? t("Analisando o conteúdo…")
            : info
              ? t("Pronto para baixar")
              : t("Adicione um link para começar");
  const progress = Number(job?.percent || 0);

  async function openOriginalLink() {
    try {
      if (window.pywebview?.api?.open_in_browser) {
        await window.pywebview.api.open_in_browser(url);
      } else {
        window.open(url, "_blank", "noopener,noreferrer");
      }
    } catch (reason) {
      setError(`Não foi possível abrir o link no navegador: ${reason.message}`);
    }
  }

  useEffect(() => {
    let active = true;
    request("/api/settings")
      .then((result) => {
        if (!active) return;
        setDownloadDir(result.download_dir);
        setDefaultDownloadDir(result.default_download_dir);
        setCanChangeDownloadDir(result.can_change_download_dir);
        setOutputTemplate(result.output_template || "{title} - {id}");
        setStartupSettingsError("");
      })
      .catch((reason) => {
        if (active) setStartupSettingsError(reason.message);
      })
      .finally(() => {
        if (active) setStartupSettingsLoaded(true);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    localStorage.setItem(LANGUAGE_KEY, language);
    document.documentElement.lang = language;
    document.title = language === "en"
      ? "SaveClip — download your media"
      : "SaveClip — seus vídeos, do seu jeito";
  }, [language]);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, 30)));
  }, [history]);

  useEffect(
    () => () => {
      eventSource.current?.close();
    },
    [],
  );

  if (!startupSettingsLoaded || startupSettingsError) {
    return (
      <main className="folder-setup-screen">
        <section className="folder-setup-card">
          <span className="folder-setup-icon"><Icon name="settings" size={22} /></span>
          <h1>{startupSettingsError ? t("Não foi possível carregar as configurações") : t("Iniciando o SaveClip…")}</h1>
          <p>{startupSettingsError ? trError(startupSettingsError) : t("Aguarde enquanto preparamos o aplicativo.")}</p>
          {startupSettingsError && (
            <button
              className="settings-done"
              onClick={() => {
                setStartupSettingsLoaded(false);
                setStartupSettingsError("");
                request("/api/settings")
                  .then((result) => {
                    setDownloadDir(result.download_dir);
                    setDefaultDownloadDir(result.default_download_dir);
                    setCanChangeDownloadDir(result.can_change_download_dir);
                    setOutputTemplate(result.output_template || "{title} - {id}");
                  })
                  .catch((reason) => setStartupSettingsError(reason.message))
                  .finally(() => setStartupSettingsLoaded(true));
              }}
            >
              Tentar novamente
            </button>
          )}
        </section>
      </main>
    );
  }

  function chooseType(type) {
    setMediaType(type);
    setPreviewError("");
    const choices = type === "audio" ? audioFormats : videoFormats;
    setFormatId(choices[0]?.format_id || "");
  }

  async function saveDownloadFolder(folder = downloadDir) {
    setSavingDownloadDir(true);
    setSettingsError("");
    try {
      const result = await request("/api/settings/download-folder", {
        download_dir: folder || null,
      });
      setDownloadDir(result.download_dir);
      setDefaultDownloadDir(result.default_download_dir);
      setSettingsError("");
    } catch (reason) {
      setSettingsError(reason.message);
    } finally {
      setSavingDownloadDir(false);
    }
  }

  async function saveOutputTemplate() {
    setSavingOutputTemplate(true);
    setSettingsError("");
    try {
      const result = await request("/api/settings/output-template", {
        output_template: outputTemplate,
      });
      setOutputTemplate(result.output_template);
    } catch (reason) {
      setSettingsError(reason.message);
    } finally {
      setSavingOutputTemplate(false);
    }
  }

  async function browseDownloadFolder() {
    try {
      const selected = await window.pywebview?.api?.select_download_folder();
      if (selected) {
        await saveDownloadFolder(selected);
      }
    } catch (reason) {
      setSettingsError(`Não foi possível abrir o seletor de pastas: ${reason.message}`);
    }
  }

  async function analyze(event) {
    event?.preventDefault();
    setError("");
    setInfo(null);
    setPreviewError("");
    setJob(null);
    setBusy(true);
    try {
      const result = await request("/api/info", { url: url.trim() });
      setInfo(result);
      setMediaType("video");
      setOutputName("");
      setPreviewError("");
      setFormatId(result.formats.find((format) => format.type === "video")?.format_id || "");
      setSelectedItems((result.items || []).map((item) => item.id));
      setView("queue");
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  }

  async function startDownload(type = mediaType, selectedFormat = formatId) {
    if (downloadActive) return;
    setError("");
    setJob({ status: "queued", percent: 0 });
    try {
      const result = await request("/api/download", {
        url: url.trim(),
        type,
        format_id: selectedFormat,
        items: isPlaylist ? selectedItems : [],
        volume_percent: type === "thumbnail" ? 100 : volumePercent,
        output_name: type === "thumbnail" ? null : outputName.trim() || null,
      });
      const source = new EventSource(`/api/progress/${result.task_id}`);
      eventSource.current?.close();
      eventSource.current = source;
      source.onmessage = async (event) => {
        let progressState;
        try {
          progressState = JSON.parse(event.data);
        } catch {
          source.close();
          setJob((current) => ({ ...current, status: "failed" }));
          setError("O SaveClip recebeu uma atualização de progresso inválida.");
          return;
        }
        setJob({
          ...progressState,
          task_id: result.task_id,
          percent: Number(progressState.percent) || 0,
          received: Number(progressState.received) || 0,
          total: Number(progressState.total) || 0,
          speed: Number(progressState.speed) || 0,
        });
        if (progressState.status === "completed") {
          source.close();
          const item = {
            id: result.task_id,
            title: progressState.title || info?.title || t("Download concluído"),
            filename: progressState.filename,
            platform: info?.platform || "SaveClip",
            date: new Date().toISOString(),
            size: Number(progressState.size || 0),
          };
          setHistory((previous) => [item, ...previous.filter((entry) => entry.id !== item.id)].slice(0, 30));
          if (isPlaylist) {
            if (!window.pywebview?.api) {
              try {
                const playlist = await request(`/api/files/${result.task_id}`);
                for (const file of playlist.files) {
                  const link = document.createElement("a");
                  link.href = `/api/file/${result.task_id}/item?filename=${encodeURIComponent(file.name)}`;
                  link.download = file.name;
                  document.body.appendChild(link);
                  link.click();
                  link.remove();
                  await new Promise((resolve) => setTimeout(resolve, 150));
                }
              } catch (reason) {
                setError(reason.message);
              }
            }
          } else {
            const link = document.createElement("a");
            link.href = `/api/file/${result.task_id}`;
            link.download = progressState.filename || "";
            document.body.appendChild(link);
            link.click();
            link.remove();
          }
        }
        if (progressState.status === "failed") {
          source.close();
          setError(progressState.error || "O download não foi concluído.");
        }
        if (progressState.status === "cancelled") source.close();
      };
      source.onerror = () => {
        if (source.readyState === EventSource.CLOSED) {
          setJob((current) => current && !TERMINAL_STATUSES.has(current.status)
            ? { ...current, status: "failed" }
            : current);
          setError("A conexão de progresso foi encerrada. Verifique o status na fila e tente novamente.");
        }
      };
    } catch (reason) {
      setJob(null);
      setError(reason.message);
    }
  }

  async function cancelDownload() {
    if (!job?.task_id || !downloadActive || job.status === "cancel_requested") return;
    setError("");
    try {
      const result = await request(`/api/download/${job.task_id}/cancel`, {});
      setJob((current) => current ? { ...current, status: result.status } : current);
      if (result.status === "cancelled") eventSource.current?.close();
    } catch (reason) {
      setError(reason.message);
    }
  }

  async function openDownloadLocation() {
    try {
      await window.pywebview.api.open_download_location(job.task_id);
    } catch (reason) {
      setError(`Não foi possível abrir o local do download: ${reason.message}`);
    }
  }

  async function pasteLink() {
    try {
      setUrl(await navigator.clipboard.readText());
      setError("");
      urlInput.current?.focus();
    } catch {
      setError("Cole o link com Ctrl+V ou permita o acesso à área de transferência.");
    }
  }

  function toggleItem(id) {
    setSelectedItems((previous) =>
      previous.includes(id) ? previous.filter((item) => item !== id) : [...previous, id],
    );
  }

  function clearCurrentItem() {
    if (downloadActive) return;
    eventSource.current?.close();
    setInfo(null);
    setJob(null);
    setUrl("");
    setOutputName("");
    setError("");
    setSelectedItems([]);
    setView("queue");
    urlInput.current?.focus();
  }

  return (
    <div className="desktop-app">
      <aside className="app-sidebar">
        <button className="app-brand" onClick={() => setView("queue")} aria-label={t("Voltar para a fila")}>
          <span className="brand-icon"><Icon name="brand" size={20} /></span>
          <span className="brand-lockup"><strong>SaveClip</strong><small>{t("Downloads locais")}</small></span>
        </button>
        <p className="sidebar-group-title">{t("Biblioteca")}</p>
        <nav className="sidebar-nav" aria-label={t("Navegação principal")}>
          <button
            className={`sidebar-link ${view === "queue" ? "sidebar-link-active" : ""}`}
            onClick={() => setView("queue")}
            aria-current={view === "queue" ? "page" : undefined}
          >
            <Icon name="video" size={17} /> <span>{t("Fila")}</span>
          </button>
          <button
            className={`sidebar-link ${view === "history" ? "sidebar-link-active" : ""}`}
            onClick={() => setView("history")}
            aria-current={view === "history" ? "page" : undefined}
          >
            <Icon name="history" size={17} /> <span>{t("Histórico")}</span>
            {history.length > 0 && <span className="sidebar-count">{history.length}</span>}
          </button>
        </nav>
        <div className="sidebar-spacer" />
        <button className="folder-shortcut" onClick={() => setSettingsOpen(true)} title={downloadDir || defaultDownloadDir}>
          <Icon name="folder" size={17} />
          <span><small>{t("Pasta de destino")}</small><strong>{downloadDir || defaultDownloadDir || t("Configurar pasta")}</strong></span>
        </button>
        <p className="sidebar-note">{t("Seus arquivos ficam neste computador.")}</p>
      </aside>

      <div className="app-main">
      <header className="app-header">
        <button className="mobile-brand" onClick={() => setView("queue")} aria-label={t("Voltar para a fila")}>
          <span className="brand-icon"><Icon name="brand" size={18} /></span>
          <span>SaveClip</span>
        </button>
        <form className="queue-input" onSubmit={analyze}>
          <input
            ref={urlInput}
            id="video-url"
            type="url"
            required
            value={url}
            onChange={(event) => {
              setUrl(event.target.value);
              setInfo(null);
              setJob(null);
              setPreviewError("");
              setError("");
            }}
            placeholder={t("Cole o link de um vídeo ou playlist para adicionar à fila")}
            aria-label={t("Link do vídeo ou publicação")}
          />
          {url && (
            <button type="button" className="icon-button input-paste" onClick={pasteLink} title={t("Colar link da área de transferência")} aria-label={t("Colar link")}>
              <Icon name="clipboard" />
            </button>
          )}
          <button type="submit" className="add-button" disabled={busy || !url.trim()} title={t("Analisar link e adicionar à fila")}>
            {busy ? <span className="spinner" /> : t("Analisar")}
          </button>
        </form>
        <button className={`icon-button settings-trigger ${settingsOpen ? "icon-button-active" : ""}`} onClick={() => setSettingsOpen(true)} title={t("Configurações")} aria-label={t("Configurações")}>
          <Icon name="settings" />
        </button>
      </header>

      <main className="workspace">
        {view === "history" ? (
          <section className="history-view">
            <div className="panel-heading">
              <div><h1>{t("Histórico de downloads")}</h1></div>
              <button className="quiet-button danger-button" disabled={!history.length} onClick={() => setHistory([])}>{t("Limpar histórico")}</button>
            </div>
            <div className="history-rows">
              {history.length === 0 && <div className="empty-history">{t("Nenhum download concluído por enquanto.")}</div>}
              {history.map((item) => (
                <article className="history-row" key={item.id}>
                  <span className="queue-file-icon"><Icon name="video" /></span>
                  <div className="queue-file-info">
                    <strong>{item.title}</strong>
                    <span>{item.platform} · {new Date(item.date).toLocaleString(language === "en" ? "en-US" : "pt-BR")}{item.size ? ` · ${prettySize(item.size)}` : ""}</span>
                  </div>
                  <span className="done-tag"><Icon name="check" size={14} /> {t("Salvo no PC")}</span>
                </article>
              ))}
            </div>
          </section>
        ) : info ? (
          <section className="queue-view" aria-label={t("Fila de downloads")}>
            <div className="panel-heading">
              <div>
                <h1>{t("Seu próximo arquivo")}</h1>
              </div>
              <button className="quiet-button" onClick={clearCurrentItem} disabled={downloadActive}>
                <Icon name="close" size={15} /> {t("Remover")}
              </button>
            </div>

            <article className="queue-card">
              <div className={`queue-thumbnail ${mediaType === "audio" && !previewUnavailable ? "queue-audio-preview" : ""}`}>
                {mediaType === "video" && !previewUnavailable ? (
                  <video
                    controls
                    preload="none"
                    referrerPolicy="no-referrer"
                    poster={info.thumbnail || undefined}
                    src={previewUrl}
                    aria-label={`${t("Prévia de vídeo:")} ${info.title}`}
                    onError={() => setPreviewError("video")}
                  >
                    {t("Seu navegador não conseguiu reproduzir esta prévia.")}
                  </video>
                ) : mediaType === "audio" && !previewUnavailable ? (
                  <div className="audio-preview">
                    {info.thumbnail && <img src={info.thumbnail} alt="" referrerPolicy="no-referrer" />}
                    <div className="audio-preview-controls">
                      <span>{t("Prévia de áudio")}</span>
                      <audio
                        controls
                        preload="none"
                        referrerPolicy="no-referrer"
                        src={previewUrl}
                        aria-label={`${t("Prévia de áudio:")} ${info.title}`}
                        onError={() => setPreviewError("audio")}
                      />
                    </div>
                  </div>
                ) : (
                  <>
                    {info.thumbnail ? <img src={info.thumbnail} alt="" referrerPolicy="no-referrer" /> : <Icon name="video" size={32} />}
                    <span className="preview-unavailable">
                      {previewError === mediaType ? t("Não foi possível reproduzir a prévia") : t("Prévia não disponível para este conteúdo")}
                    </span>
                  </>
                )}
                {mediaType === "video" && info.duration != null && <span className="queue-duration">{prettyDuration(info.duration, language)}</span>}
              </div>
              <div className="queue-file-info">
                <div className="queue-meta">
                  <span className="platform-tag">{info.platform}</span>
                  {isPlaylist && <span className="platform-tag playlist-tag">{t("Playlist")} · {info.items.length}{t(" itens")}</span>}
                </div>
                <h2>{info.title}</h2>
                <p>{info.author || t("Autor indisponível")}</p>
                <div className="output-name">
                  <label htmlFor="output-name">{t(isPlaylist ? "Nome da pasta" : "Nome do arquivo")}</label>
                  <input
                    id="output-name"
                    type="text"
                    value={outputName}
                    maxLength={120}
                    disabled={downloadActive}
                    placeholder={t(isPlaylist ? "Usar o título da playlist" : "Usar o título original")}
                    autoComplete="off"
                    onChange={(event) => setOutputName(event.target.value)}
                  />
                  <span>{isPlaylist ? t("Os itens selecionados serão salvos em uma pasta.") : `${t("A extensão será adicionada automaticamente")}.`}</span>
                </div>
                <div className="output-volume">
                  <div className="output-volume-heading">
                    <label htmlFor="output-volume">{t("Volume do arquivo")}</label>
                    <output htmlFor="output-volume">{volumePercent}%</output>
                  </div>
                  <input
                    id="output-volume"
                    type="range"
                    min="0"
                    max="200"
                    step="5"
                    value={volumePercent}
                    disabled={downloadActive}
                    aria-valuetext={`${volumePercent}%`}
                    onChange={(event) => setVolumePercent(Number(event.target.value))}
                  />
                  <span>{t("100% mantém o áudio original; acima disso pode haver distorção.")}</span>
                </div>
                {info.thumbnail && (
                  <button disabled={downloadActive} onClick={() => startDownload("thumbnail", "thumbnail")} className="thumbnail-button">
                    {t("Baixar miniatura")}
                  </button>
                )}
              </div>
            </article>

            {isPlaylist && (
              <section className="playlist-items">
                <div className="playlist-heading">
                  <span>{t("Itens para incluir")}</span>
                  <button onClick={() => setSelectedItems(selectedItems.length === info.items.length ? [] : info.items.map((item) => item.id))}>
                    {selectedItems.length === info.items.length ? t("Desmarcar todos") : t("Selecionar todos")}
                  </button>
                </div>
                <div className="playlist-list">
                  {info.items.map((item, index) => (
                    <label className="playlist-item" key={item.id}>
                      <input type="checkbox" checked={selectedItems.includes(item.id)} disabled={downloadActive} onChange={() => toggleItem(item.id)} />
                      <span>{index + 1}</span>
                      <strong>{item.title}</strong>
                    </label>
                  ))}
                </div>
              </section>
            )}

            {job && (
              <section className={`download-progress ${["failed", "cancelled"].includes(job.status) ? "progress-failed" : ""}`} aria-live="polite">
                <div className="progress-heading">
                  <span>{job.status === "completed" ? t("Arquivo salvo no computador") : job.status === "failed" ? t("Não foi possível concluir") : job.status === "cancelled" ? t("Download cancelado") : job.status === "cancel_requested" ? t("Cancelando download…") : job.status === "analyzing" ? t("Analisando o conteúdo…") : job.status === "processing" ? t("Preparando arquivo…") : job.status === "queued" ? t("Aguardando na fila…") : t("Baixando para este computador…")}</span>
                  <strong>{job.status === "failed" ? t("Falhou") : job.status === "cancelled" ? t("Cancelado") : job.status === "completed" ? "100%" : ["queued", "analyzing"].includes(job.status) ? "…" : `${Math.round(progress)}%`}</strong>
                </div>
                <div className={`progress-track ${["queued", "analyzing"].includes(job.status) ? "progress-indeterminate" : ""}`}><div style={{ width: `${["failed", "cancelled"].includes(job.status) ? 0 : Math.min(100, Math.max(0, progress))}%` }} /></div>
                <div className="progress-actions">
                  <span className="progress-detail">
                    {job.received > 0
                      ? `${prettySize(job.received)}${job.total > 0 ? `${t(" de ")}${prettySize(job.total)}` : ""}`
                      : job.status === "analyzing"
                        ? t("Obtendo informações da plataforma; a porcentagem aparece quando o download começar.")
                        : job.status === "queued"
                          ? t("O download começará assim que sair da fila.")
                          : t("Aguardando os primeiros dados do download.")}
                  </span>
                  {downloadActive && <button className="quiet-button" onClick={cancelDownload} disabled={job.status === "cancel_requested"}>{job.status === "cancel_requested" ? t("Cancelando…") : t("Cancelar download")}</button>}
                  {job.status === "completed" && window.pywebview?.api?.open_download_location && (
                    <button className="quiet-button" onClick={openDownloadLocation}>
                      <Icon name="folder" size={14} /> {t(isPlaylist ? "Abrir pasta do download" : "Abrir local do download")}
                    </button>
                  )}
                </div>
              </section>
            )}
          </section>
        ) : (
          <section className="empty-queue">
            <div className="empty-copy">
              <h1>{error ? t("Não foi possível adicionar") : t("Sua fila está vazia")}</h1>
              <p>{error ? trError(error) : t("Cole um link no campo acima para conferir a miniatura, o título e os formatos disponíveis.")}</p>
              {!error && (
                <span className="empty-destination">
                  <Icon name="folder" size={16} />
                  <span>{t("Salvos em")}<strong title={downloadDir || defaultDownloadDir}>{downloadDir || defaultDownloadDir || t("sua pasta de downloads")}</strong></span>
                </span>
              )}
              {error && !isAgeRestrictionError(error) && <button className="quiet-button" onClick={() => setError("")}>{t("Entendi")}</button>}
            </div>
            <div className="empty-preview" role="img" aria-label={t("A prévia do vídeo ou áudio aparecerá aqui")}>
              <Icon name="video" size={30} />
              <span>{t("A prévia aparece após a análise")}</span>
            </div>
          </section>
        )}
      </main>

      <footer className="bottom-panel">
        <div className={`status-bar ${["failed", "cancelled"].includes(job?.status) ? "status-error" : ""}`}>
          <span className="status-dot" />
          <span>{statusLabel}</span>
          {job && !["failed", "cancelled"].includes(job.status) && (
            <div className="status-progress"><span style={{ width: `${job.status === "completed" ? 100 : Math.min(100, Math.max(0, progress))}%` }} /></div>
          )}
          {error && <span className="status-error-detail" title={trError(error)}>{trError(error)}</span>}
          {isAgeRestrictionError(error) && (
            <button className="quiet-button status-action" onClick={openOriginalLink}>{t("Abrir no site oficial")}</button>
          )}
        </div>
        {view === "queue" && <div className="bottom-toolbar">
          <button className={`type-button ${mediaType === "video" ? "type-selected" : ""}`} onClick={() => chooseType("video")} disabled={!info || !videoFormats.length} aria-pressed={mediaType === "video"}>
            <Icon name="video" size={15} /> {t("Vídeo")}
          </button>
          <button className={`type-button ${mediaType === "audio" ? "type-selected" : ""}`} onClick={() => chooseType("audio")} disabled={!info || !audioFormats.length} aria-pressed={mediaType === "audio"}>
            {t("Áudio")}
          </button>
          <select className="quality-select" value={formatId} onChange={(event) => setFormatId(event.target.value)} disabled={!info || !availableFormats.length || downloadActive} aria-label={t("Qualidade ou formato")}>
            {availableFormats.length
              ? availableFormats.map((format) => <option value={format.format_id} key={format.format_id}>{t(format.label)}</option>)
              : <option value="">{info ? t("Indisponível") : t("Qualidade")}</option>}
          </select>
          <button className="toolbar-icon clear-button" title={t("Limpar fila")} aria-label={t("Limpar fila")} disabled={!info || downloadActive} onClick={clearCurrentItem}>
            <Icon name="trash" />
          </button>
          <button className="download-button" disabled={!info || !formatAvailable || busy || downloadActive || (isPlaylist && selectedItems.length === 0)} onClick={() => startDownload()}>
            <Icon name="download" size={16} /> {t("Baixar")}
          </button>
        </div>}
      </footer>

      {settingsOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSettingsOpen(false); }}>
          <section className="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title">
            <div className="settings-heading">
              <div><h2 id="settings-title">{t("Configurações")}</h2></div>
              <button className="icon-button" onClick={() => setSettingsOpen(false)} aria-label={t("Fechar configurações")}><Icon name="close" /></button>
            </div>
            <div className="settings-option">
              <div><strong>{t("Idioma da interface")}</strong></div>
              <select
                className="quality-select language-select"
                value={language}
                onChange={(event) => setLanguage(event.target.value)}
                aria-label={t("Idioma")}
              >
                <option value="pt-BR">{t("Português (Brasil)")}</option>
                <option value="en">{t("Inglês")}</option>
              </select>
            </div>
            <div className="settings-option">
              <div><strong>{t("Tema da interface")}</strong><span>{t("Personalize as cores do SaveClip.")}</span></div>
              <button className="quiet-button" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? t("Escuro") : t("Claro")}</button>
            </div>
            {canChangeDownloadDir && (
              <div className="settings-option settings-folder-option">
                <div><strong>{t("Padrão do nome dos arquivos")}</strong><span>{t("Campos disponíveis:")} {"{title}"}, {"{id}"} {language === "en" ? "and" : "e"} {"{uploader}"}.</span></div>
                <div className="download-folder-controls">
                  <input
                    className="download-folder-input"
                    value={outputTemplate}
                    onChange={(event) => setOutputTemplate(event.target.value)}
                    aria-label={t("Padrão para nomes de arquivos")}
                    placeholder="{title} - {id}"
                    maxLength={160}
                  />
                  <button className="quiet-button" onClick={saveOutputTemplate} disabled={savingOutputTemplate || !outputTemplate.trim()}>
                    {savingOutputTemplate ? t("Salvando…") : t("Salvar padrão")}
                  </button>
                </div>
              </div>
            )}
            <div className={`settings-option ${canChangeDownloadDir ? "settings-folder-option" : ""}`}>
              <div><strong>{t("Local dos downloads")}</strong><span>{canChangeDownloadDir ? t("Escolha onde os próximos arquivos serão salvos.") : t("Pasta definida pela configuração do servidor.")}</span></div>
              {canChangeDownloadDir ? (
                <div className="download-folder-controls">
                  <input
                    className="download-folder-input"
                    value={downloadDir}
                    onChange={(event) => setDownloadDir(event.target.value)}
                    aria-label={t("Pasta dos downloads")}
                    placeholder={t("Escolha uma pasta")}
                  />
                  <button className="quiet-button" onClick={browseDownloadFolder} disabled={savingDownloadDir || !window.pywebview?.api}>
                    {t("Escolher e salvar…")}
                  </button>
                  <button className="quiet-button" onClick={() => saveDownloadFolder()} disabled={savingDownloadDir || !downloadDir.trim()}>
                    {savingDownloadDir ? t("Salvando…") : t("Salvar")}
                  </button>
                  <button className="quiet-button" onClick={() => saveDownloadFolder("")} disabled={savingDownloadDir || downloadDir === defaultDownloadDir}>
                    {t("Padrão")}
                  </button>
                </div>
              ) : <code>{downloadDir}</code>}
            </div>
            {settingsError && <p className="settings-error" role="alert">{trError(settingsError)}</p>}
            <div className="legal-copy">
              <strong>{t("Use com responsabilidade")}</strong>
              <p>{t(LEGAL_NOTICE)}</p>
              <p>{t("O SaveClip não remove DRM, não usa cookies de sessão e não contorna login ou outras restrições de acesso.")}</p>
            </div>
            <button className="settings-done" onClick={() => setSettingsOpen(false)}>{t("Concluído")}</button>
          </section>
        </div>
      )}

      </div>
    </div>
  );
}

export default App;
