# SaveClip

Aplicação web para analisar links e salvar conteúdos próprios, de domínio público ou autorizados. A extração usa yt-dlp sem cookies de sessão e não tenta contornar DRM, login, paywalls ou restrições de idade.

## Abrir diretamente no Windows

O executável abre uma janela desktop nativa do Windows para o SaveClip (usando WebView2 para renderizar a interface), sem abrir uma aba ou exibir controles do navegador. O pacote é instalado em uma pasta para iniciar mais rápido; ele roda sem Docker, Redis, Node.js ou instalação separada do ffmpeg:

- Para abrir sem compilar, dê dois cliques em `dist\SaveClip.exe` ou use `Abrir-SaveClip.bat`. Mantenha a pasta `dist` inteira, incluindo `_internal`.
- O executável do Windows usa como ícone a imagem fornecida para o SaveClip.
- Ao abrir, o SaveClip vai direto para a tela principal. A pasta padrão pode ser configurada a qualquer momento em **Configurações > Local dos downloads**; enquanto isso, o app usa a pasta padrão do sistema.
- O aviso legal não bloqueia mais a abertura; ele continua disponível em **Configurações** e nesta documentação.
- Use `Build-SaveClip.bat` somente quando quiser gerar uma nova versão do programa após alterações no código. A build requer Python 3 e Node.js; o executável pronto não compila Python quando é aberto.
- Para preparar um instalador para outras pessoas, execute `Build-Installer.bat`. O script recompila a interface e o executável antes de criar `dist\installer\SaveClip-Setup.exe`, evitando empacotar uma build antiga. Feche o SaveClip antes de iniciar. O instalador instala o app por usuário e cria um atalho no menu Iniciar. A pasta de downloads pode ser configurada em **Configurações**; para gerar o instalador no seu computador, instale o Inno Setup 6. Quem receber o instalador não precisa dele.
- Feche a janela do SaveClip antes de iniciar outro build. Ela mantém o servidor ligado; `Ctrl+C` ou fechar a janela encerra o aplicativo.
- Os downloads, o histórico de tarefas e os logs ficam em `%LOCALAPPDATA%\SaveClip`. O servidor HTTP fica restrito ao próprio computador e a interface aparece dentro da janela do app.
- Em **Configurações > Local dos downloads**, escolha e salve uma pasta pelo seletor do Windows, informe um caminho manualmente e pressione **Salvar**, ou restaure o local padrão. A preferência fica salva em `%LOCALAPPDATA%\SaveClip\settings.json` e é carregada nas próximas aberturas; downloads em andamento precisam terminar antes da troca.
- O Microsoft Edge WebView2 Runtime é necessário para mostrar a janela desktop; ele já costuma estar disponível no Windows 10/11.

O executável é um build local de desenvolvimento para Windows. Cada novo build atualiza `dist\SaveClip.exe` e a pasta `_internal`, mantendo o aplicativo independente dos serviços usados no deploy. Não mova apenas o `.exe`.

> **Aviso legal:** Use apenas para conteúdos próprios, de domínio público ou com autorização do autor. O usuário é responsável por respeitar os direitos autorais e os Termos de Serviço de cada plataforma.

## Recursos

- Análise de links públicos de YouTube (incluindo Shorts), Instagram, TikTok, Facebook, X/Twitter, Pinterest,Não há tentativa de contornar login, restrições de idade, DRM ou proteções dos sites.
- Informações do conteúdo, miniatura, autor, duração e resoluções disponíveis.
- Escolha da pasta de destino no app desktop; quando a plataforma não informa resoluções, o vídeo ainda pode ser baixado na melhor qualidade disponível.
- No app desktop, os arquivos concluídos ficam diretamente na pasta escolhida com nomes configuráveis; pastas técnicas por tarefa são usadas apenas temporariamente e ficam ocultas.
- Depois de analisar um vídeo ou áudio, é possível informar um nome opcional para o arquivo; a extensão é aplicada automaticamente. Em downloads com vários itens selecionados, o nome é usado no arquivo ZIP.
- Ao concluir um download no app desktop, use **Abrir local do download** para abrir o Explorador de Arquivos com o arquivo selecionado.
- Download de vídeo, áudio MP3/M4A/WAV, miniaturas e seleção de itens de playlists/carrosséis.
- Prévia de vídeo e áudio no app, quando a plataforma oferece um formato reproduzível no navegador; em playlists, a prévia é do primeiro item.
- Volume de saída ajustável de 0% a 200% para vídeos e áudio. Em 100%, o áudio original é preservado sem reprocessamento; outros valores reprocessam o áudio com FFmpeg, sem recodificar a faixa de vídeo. Volumes acima de 100% podem causar distorção.
- Para vídeos do X/Twitter, o áudio também é oferecido quando o yt-dlp não consegue identificar o codec nas variantes de vídeo.
- Fila Redis/RQ, atualizações de progresso via Server-Sent Events e download do arquivo final.
- Estados de tarefa rastreáveis, cancelamento cooperativo e concorrência limitada no app desktop.
- Padrão de nome configurável no app desktop com os campos `{title}`, `{id}` e `{uploader}`.
- Histórico local no navegador, temas claro/escuro e layout responsivo em português do Brasil.
- Interface disponível em português do Brasil e inglês; a preferência de idioma fica salva neste computador.
- Validação de esquema, allowlist de domínios, resolução DNS pública, limite por IP, limites de duração/tamanho e expiração dos arquivos temporários.

Conteúdos privados, indisponíveis, com restrição de idade ou protegidos por DRM não são contornados. Se a análise indicar restrição de idade, use **Abrir no site oficial** para acessar a plataforma e siga a verificação disponibilizada por ela; o SaveClip não importa cookies nem credenciais do navegador.

## Executar com Docker

1. Instale Docker Desktop (ou Docker Engine com Compose).
2. Copie `.env.example` para `.env` e ajuste os limites conforme necessário.
3. Na raiz do projeto:

   ```powershell
   docker compose up --build
   ```

4. Abra [http://localhost:8080](http://localhost:8080). Para encerrar, use `Ctrl+C`; para encerrar e remover containers, execute `docker compose down`.

Os downloads ficam em um volume Docker compartilhado entre API e worker. Redis é interno à rede Compose e não publica uma porta no host.

## Execução local para desenvolvimento

### Backend

Requer Python 3.11+, Redis e ffmpeg disponíveis no `PATH`.

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:REDIS_URL = "redis://localhost:6379/0"
$env:DOWNLOAD_DIR = "$PWD\downloads"
uvicorn app.main:app --reload
```

Em outro terminal, com o mesmo ambiente:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
$env:REDIS_URL = "redis://localhost:6379/0"
$env:DOWNLOAD_DIR = "$PWD\downloads"
rq worker -u redis://localhost:6379/0 downloads
```

### Frontend

Requer Node.js 20+ e npm:

```powershell
cd frontend
npm install
npm run dev
```

Abra [http://localhost:5173](http://localhost:5173). O Vite encaminha `/api` para `http://localhost:8000`; use `API_PROXY_TARGET` para alterar esse endereço.

## Configuração

As variáveis são lidas do ambiente ou do `.env` pelo Docker Compose:

| Variável | Padrão | Descrição |
|---|---:|---|
| `APP_PORT` | `8080` | Porta HTTP da interface |
| `MAX_DURATION_SECONDS` | `7200` | Duração máxima por vídeo |
| `MAX_FILE_SIZE_BYTES` | `2147483648` | Tamanho máximo por download |
| `MAX_CONCURRENT_DOWNLOADS` | `2` | App desktop: downloads simultâneos (limitado a 1–4) |
| `OUTPUT_TEMPLATE` | `{title} - {id}` | App desktop: padrão para nomes dos arquivos |
| `FILE_TTL_MINUTES` | `25` | Expiração de arquivos temporários |
| `RATE_LIMIT_REQUESTS` | `10` | Requisições por janela e endereço IP |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Janela do limite por IP |
| `CORS_ORIGINS` | `http://localhost:8080,http://localhost:5173` | Origens autorizadas para chamadas diretas à API |
| `EXTRA_ALLOWED_DOMAINS` | vazio | Domínios adicionais separados por vírgula |
| `LOG_LEVEL` | `INFO` | Nível de logs do backend |

Use domínios adicionais somente quando confiar neles. Isso não habilita indiscriminadamente qualquer site: a extração continua sujeita aos extratores suportados pelo yt-dlp e à validação de domínio/endereço público. O backend aceita apenas HTTP(S), rejeita credenciais na URL, portas personalizadas e endereços privados/locais. As prévias são reproduzidas diretamente no player do app, sem cookies; algumas plataformas/formats não permitem reprodução no navegador e podem não oferecer prévia.

`MAX_CONCURRENT_DOWNLOADS` limita a 1–4 downloads simultâneos no app desktop. No Docker, a fila Redis/RQ processa tarefas pelos workers; aumente a concorrência escalando cuidadosamente as réplicas do serviço `worker`. O cancelamento é cooperativo: é aplicado quando yt-dlp verifica o estado da tarefa, portanto pode levar algum tempo se a operação estiver aguardando uma resposta de rede.

No app desktop, o padrão de nome aceita somente `{title}`, `{id}` e `{uploader}`. Esses campos são sanitizados antes de serem usados no caminho de saída. A configuração é persistida junto com a pasta padrão sem sobrescrever essa preferência.

O nome opcional informado em cada download substitui o padrão apenas para aquela tarefa. Deixe o campo vazio para usar o nome original/padrão configurado. O SaveClip rejeita separadores de caminho, caracteres inválidos e nomes reservados do Windows; não é necessário digitar a extensão.

As opções de resolução e áudio exibidas vêm dos formatos informados pelo yt-dlp para aquele conteúdo; formatos ausentes ou marcados como DRM não são oferecidos. A lista limitada a 50 itens de playlist/carrossel permite selecionar o que será enfileirado.

## API

- `POST /api/info` — recebe `{"url":"..."}` e retorna metadados, formatos e itens de playlists.
- `POST /api/download` — recebe `{"url":"...","format_id":"video_720","type":"video","items":["1"]}` e retorna `task_id`.
- `GET /api/progress/{task_id}` — fluxo SSE com estado e progresso.
- `GET /api/file/{task_id}` — entrega o arquivo final enquanto não expirar.
- `GET /api/health` — estado da API, Redis e versão do yt-dlp.

Consulte `/docs` no backend durante o desenvolvimento para a documentação OpenAPI.

## Atualizar yt-dlp

Atualização manual e confirmada no ambiente Python. O script consulta a versão e o hash publicados pelo PyPI, baixa apenas um wheel oficial compatível, confere o SHA-256 e não instala dependências transitivas. A instalação só ocorre depois da confirmação interativa:

```powershell
cd backend
py -m app.update_ytdlp
```

O hash é comparado com os metadados oficiais do PyPI recebidos por HTTPS; isso não equivale a uma assinatura independente do publicador. Para atualizar o aplicativo desktop distribuído, atualize o ambiente de build e execute `Build-SaveClip.bat`; o executável não se atualiza sozinho.

No Docker, atualize a dependência declarada em `backend/requirements.txt` de forma revisada e recrie as imagens; não atualize o worker silenciosamente em execução:

```powershell
docker compose build --pull backend worker
docker compose up -d --force-recreate backend worker
```

## Testes

```powershell
cd backend
py -m pip install -r requirements.txt
py -m pytest -q
```

O build do frontend pode ser verificado com `cd frontend; npm install; npm run build`.

### Testar a versão desktop sem criar o executável

O launcher também pode ser iniciado pelo Python, útil durante o desenvolvimento:

```powershell
python backend\launcher.py
```

Esse modo desktop usa uma fila local e SQLite, mas ainda requer que as dependências Python estejam instaladas e que a interface tenha sido compilada (`cd frontend; npm ci; npm run build`).

## Privacidade e segurança

Os arquivos baixados são apagados após o prazo configurado; o histórico fica apenas no `localStorage` do navegador. Redis não é exposto à rede do host. Não configure cookies, credenciais de plataforma ou mecanismos de contorno de acesso. Em uma instalação pública, coloque a aplicação atrás de HTTPS e configure `CORS_ORIGINS` para as origens reais.

## Utilitário local de links diretos

O utilitário independente de links diretos permanece disponível nos arquivos `app.py`, `index.html`, `style.css` e `app.js`. Ele é separado do SaveClip desktop e não extrai páginas de plataformas.
