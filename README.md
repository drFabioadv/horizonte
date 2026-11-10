# HORIZONTE — Direito. Política. Sociedade.

> Informação com contexto. Análise com responsabilidade. Opinião com fundamento.

O HORIZONTE é uma central editorial que roda **no seu computador, de graça**. Ele:

1. acompanha o noticiário por RSS (Câmara, Senado, TCU, Planalto, gov.br, Agência Brasil, G1, Folha, Estadão, BBC, CNN, O Liberal, Conjur, JOTA e outras);
2. agrupa as notícias que tratam do mesmo fato e **verifica** cada fato pelas fontes (fonte primária, veículos independentes, data, sinais de contestação);
3. escolhe as pautas do dia equilibrando **Direito e Justiça, Política e Instituições, Sociedade e Cidadania**;
4. escreve uma análise crítica e institucional com a IA local (Ollama), passando por **travas contra invenção**;
5. **publica sozinho no LinkedIn** pela API oficial, depois que você conecta a conta e liga o modo automático;
6. prepara os conteúdos do **X** para você publicar à mão, na Central do X;
7. gera o **Relatório Diário HORIZONTE**, além dos semanais e mensais, com exportação em PDF e CSV.

Tudo fica salvo em `data/horizonte.db` (SQLite), inclusive depois de reiniciar.

---

## 1. Requisitos

| Item | Para quê | Custo |
|---|---|---|
| Windows 10/11 (também roda em Linux e macOS) | rodar o sistema | — |
| [Python 3.11 ou mais novo](https://www.python.org/downloads/) | backend | grátis |
| [Ollama](https://ollama.com/download) + um modelo (ex.: `gemma4:12b`) | escrever as análises | grátis |
| Conta no LinkedIn + app no LinkedIn Developers | publicar no seu perfil | grátis |
| Computador ligado e conectado | rotinas automáticas | — |

Com uma placa de vídeo de 16 GB, os modelos `gemma4:12b` (padrão) e `qwen3:14b` rodam bem.

## 2. Instalação (Windows)

1. Instale o Python e marque **"Add python.exe to PATH"**.
2. Copie a pasta `horizonte` para um lugar fixo, por exemplo `C:\HORIZONTE`.
3. Dê dois cliques em **`instalar.bat`**. Ele cria o ambiente `.venv`, instala as dependências e cria o arquivo `.env`.
4. Instale o Ollama e, no Prompt de Comando, baixe o modelo:
   ```
   ollama pull gemma4:12b
   ```
5. Configure o LinkedIn (seção 5).
6. Dê dois cliques no ícone **HORIZONTE** que apareceu na **área de trabalho** (o instalador cria esse atalho e outro no menu Iniciar; se faltar, rode `criar_atalhos.bat`).
   - O HORIZONTE fica na **bandeja do sistema**, perto do relógio. Clique no ícone para abrir o painel já logado. Com o botão direito, o menu tem: abrir painel, rodar ciclo agora, pausar/retomar e sair.
   - Para fixar na **barra de tarefas**: botão direito no ícone da área de trabalho → *Mostrar mais opções* → *Fixar na barra de tarefas*.
7. Se abrir o painel por outro caminho, entre com a **chave do painel**, que fica no arquivo `data/admin.token`. Se preferir uma chave sua, defina `HORIZONTE_ADMIN_TOKEN` no `.env`.

O `iniciar.bat` continua existindo para quem preferir ver a janela de registros (útil para diagnosticar problemas).

Linux/macOS: `./iniciar.sh`.

## 3. Configuração

- **`.env`**: segredos e infraestrutura (LinkedIn, Ollama, porta, fuso). Veja o `.env.example`, que é comentado linha a linha. O `.env` nunca vai para o Git.
- **Painel → Configurações → Geral**:
  - metas diárias (padrão: 3 no LinkedIn e 3 para o X);
  - horários do LinkedIn (padrão: 08:30, 12:30 e 18:30);
  - equilíbrio entre as três áreas (34/33/33);
  - horário do ciclo diário (06:30) e do relatório (22:00);
  - intervalo do radar (60 min) e idade máxima da notícia (48 h);
  - assinatura dos posts, rodapé opcional de "apoio de IA", modelo do Ollama e notificações do Windows.
- **Painel → Configurações → Fontes**: ligar e desligar fontes, trocar o feed, **testar** (o HORIZONTE procura o RSS sozinho), definir a política de imagem e adicionar fontes novas.

## 4. Inicialização automática

- Dê dois cliques em **`instalar_inicio_automatico.bat`**. O HORIZONTE passa a abrir na **bandeja, sem janela**, toda vez que você entra no Windows. Para desfazer, use `remover_inicio_automatico.bat`.
- Se o servidor interno cair, a bandeja o religa sozinha em 15 segundos (o `iniciar.bat` faz o mesmo).
- Se você clicar no ícone com o HORIZONTE já aberto, ele só abre o painel, sem abrir uma segunda cópia.
- **Deixe o computador ligado**: em *Configurações do Windows → Sistema → Energia*, coloque "Suspender" como **Nunca** quando estiver na tomada. Com o PC desligado nada roda; quando ele ligar, o ciclo do dia é feito na hora.

## 5. Conexão com o LinkedIn (API oficial, gratuita)

1. Acesse <https://www.linkedin.com/developers/apps> e clique em **Create app**.
   - O LinkedIn exige que todo app esteja ligado a uma **Página do LinkedIn**. Você pode criar uma página gratuita (por exemplo, "HORIZONTE"). Os posts continuam saindo no **seu perfil pessoal**.
2. Na aba **Products**, adicione:
   - **Share on LinkedIn**, que dá a permissão `w_member_social`;
   - **Sign In with LinkedIn using OpenID Connect**, que dá `openid` e `profile`.
3. Na aba **Auth**, em *Authorized redirect URLs*, cadastre exatamente:
   ```
   http://localhost:8787/api/linkedin/callback
   ```
4. Copie o **Client ID** e o **Client Secret** para o `.env` (`LINKEDIN_CLIENT_ID` e `LINKEDIN_CLIENT_SECRET`) e reinicie o HORIZONTE.
5. No painel, vá em **LinkedIn → Conectar conta do LinkedIn** e autorize.
6. Faça a **publicação de teste**. Ela é visível só para suas conexões e pode ser apagada depois.
7. Ligue o **Modo automático**.

**Validade:** o token do LinkedIn dura cerca de **60 dias**, e apps gratuitos não recebem renovação automática. O painel mostra quantos dias faltam e avisa quando faltar uma semana; basta clicar em **Reconectar**.

## 6. Como funciona a rotina automática

| Quando | O que acontece |
|---|---|
| A cada 60 min | **Radar**: lê os feeds, deduplica, classifica e verifica. |
| 06:30 | **Ciclo diário**: radar → reverificação → seleção equilibrada → análise com a IA → posts do LinkedIn agendados → conteúdos do X prontos. |
| Durante o dia | Se faltou pauta (ex.: a IA estava desligada), o radar completa a meta quando for possível. |
| 08:30 / 12:30 / 18:30 | **Publicação no LinkedIn**, se o modo automático estiver ligado. Antes de publicar, a pauta é **reverificada**. |
| 22:00 | **Relatório diário**. Os semanais saem na segunda-feira e os mensais no dia 1. |

**Sem duplicidade:** cada rotina é registrada com chave única (tarefa + horário). Reiniciar o PC não repete nada. Um post que estava sendo publicado quando o PC desligou fica como **"Conferir no LinkedIn"** e não é republicado às cegas.

**Pausar:** o botão **Pausar** na barra lateral interrompe todas as rotinas até você retomar.

## 7. Verificação e travas editoriais

Status de cada fato (grupo de notícias):

- **VERIFICADA**: há fonte primária (o próprio órgão), dois ou mais veículos independentes, ou a Agência Brasil em tema sem risco.
- **EM CONFERÊNCIA**: uma única fonte jornalística, ou acusação grave sem fonte primária nem três veículos. Ausência de confirmação **não** significa que a notícia é falsa.
- **CONTROVERSA**: as fontes trazem negação, desmentido ou contestação.
- **NÃO PUBLICAR**: notícia antiga, só opinião/vídeo/áudio, ou sem relevância pública.

Só pautas **VERIFICADAS** viram conteúdo. Antes de salvar, o texto da IA passa por travas que conferem:

- números que não aparecem nas fontes;
- citações entre aspas que não estão nas fontes;
- projeto de lei, PEC ou MP tratado como lei aprovada;
- afirmação de culpa sem condenação nas fontes;
- linguagem de campanha partidária.

Se a trava falhar duas vezes, a pauta é **suspensa** com o motivo, e o HORIZONTE não completa a meta com material fraco. As fontes, a assinatura e os links são acrescentados pelo próprio sistema, nunca pela IA.

## 8. Central do X

O X não tem publicação automática, porque a API dele é paga. Para cada pauta, a Central do X mostra:

- título, categoria e data da notícia;
- texto pronto, ou thread, com a contagem de caracteres;
- botões para **copiar**, **abrir a fonte**, **abrir a imagem** e **abrir o X**;
- imagem **só quando há autorização**: ou a fonte foi marcada por você como "reuso com crédito", ou a imagem foi enviada por você. Sem autorização, aparece o aviso e o link da publicação original;
- situação: **PRONTO PARA PUBLICAR** ou **PUBLICADO MANUALMENTE**. Só você marca como publicado.

## 9. Imagens e direitos autorais

Por padrão, **nenhuma fonte tem imagem liberada**. A Agência Brasil, por exemplo, autoriza reprodução "para veículos de comunicação com fins jornalísticos, mediante indicação da fonte", e uso em redes sociais pode exigir licenciamento. Confira a política de cada fonte antes de mudar para **"Reuso com crédito"** em *Configurações → Fontes*. O HORIZONTE nunca remove créditos e não gera imagens novas.

## 10. Solução de problemas

| Sintoma | O que fazer |
|---|---|
| Painel não abre | Veja se o ícone do HORIZONTE está na bandeja (setinha ^ perto do relógio). Se a porta 8787 estiver ocupada por outro programa, mude `HORIZONTE_PORT` no `.env` (ex.: 8788) e o endereço de retorno no app do LinkedIn. |
| "IA local não encontrada" | Abra o Ollama. No terminal, `ollama list` precisa mostrar o modelo configurado. |
| Pautas "Aguardando IA local" | Ligue o Ollama. O radar seguinte produz as pautas pendentes, ou use **Rodar ciclo do dia agora**. |
| LinkedIn "Não configurado" | Preencha `LINKEDIN_CLIENT_ID` e `LINKEDIN_CLIENT_SECRET` no `.env` e reinicie. |
| Erro de redirect ao conectar | O endereço de retorno no app precisa ser **idêntico** a `http://localhost:8787/api/linkedin/callback`. |
| Post "Falhou (403)" | O app não tem o produto **Share on LinkedIn** ativo. |
| Post "Falhou (401)" | A autorização venceu ou foi revogada. Clique em **Reconectar**. |
| Fonte com erro | *Configurações → Fontes → Testar*. Sites mudam de endereço de RSS com frequência. |
| Esqueci a chave do painel | Abra `data/admin.token`. |

Os registros ficam em *Configurações → Registros* e no arquivo `data/horizonte.log`, sempre sem tokens.

## 11. Limitações do modo gratuito (o que você precisa saber)

- **Órgãos sem RSS público funcionando** (STF, STJ, TST, CNJ, TJPA, TRT-8, MPPA, TCE-PA, ALEPA, Agência Pará, DOU): entram desligados. As decisões desses órgãos chegam pela Agência Brasil, Conjur, JOTA e outros veículos. Use **Testar** de vez em quando: se algum passar a ter feed, é só ligar.
- **A verificação é por evidências, não infalível.** Ela confirma que o fato foi noticiado pela fonte oficial ou por veículos independentes, e a data. Ela **não** lê o processo inteiro nem o texto integral da lei. Em temas jurídicos, os posts trazem o link oficial para conferência.
- **As travas cobrem os erros mais perigosos** (números, citações, PL como lei, culpa, campanha), mas não toda interpretação possível. **Recomendação:** nos primeiros dias, deixe o modo automático desligado, leia os textos no painel e só depois ligue.
- **LinkedIn:** reconexão a cada ~60 dias. Os limites de uso do LinkedIn valem; se forem atingidos, o post é reagendado.
- **X:** publicação manual por decisão de custo zero.
- **Qualidade do texto** depende do modelo local. Modelos maiores escrevem melhor, mas são mais lentos.
- **O PC precisa estar ligado** nos horários. Se estiver desligado, o ciclo roda quando ele ligar, e os posts atrasados são espaçados.

## 12. Segurança

- O painel só responde neste computador (`127.0.0.1`), e tudo exige a chave do painel.
- O token do LinkedIn fica **criptografado** no banco, com a chave `HORIZONTE_SECRET_KEY` ou `data/secret.key`.
- Os logs mascaram tokens e segredos.
- `.env`, `data/`, o banco e as chaves estão no `.gitignore`.
- Conexão só por OAuth: o HORIZONTE **nunca pede sua senha**.
- **Desconectar** revoga o token e desliga o modo automático.
- **Não apague a pasta `data/`**: ela guarda todo o histórico editorial.

## 13. Testes

```
.venv\Scripts\python.exe -m pytest
```

Os testes simulam a internet, o Ollama e o LinkedIn. Eles cobrem radar, deduplicação, agrupamento, verificação, seleção equilibrada, produção com travas, imagens autorizadas, OAuth, publicação, troca de versão da API, erros 401, 429 e 426, recuperação após queda, Central do X, relatórios em PDF e CSV, agendador sem duplicidade e API do painel com login.

## 14. Estrutura

```
horizonte/
  config.py      preferências padrão e leitura do .env
  db.py          banco SQLite e histórico
  sources.py     fontes padrão e descoberta de RSS
  radar.py       leitura dos feeds
  classify.py    categoria, região, relevância e alertas
  verify.py      agrupamento por fato e verificação
  llm.py         IA local (Ollama)
  editorial.py   seleção, análise, travas e textos por rede
  images.py      política de imagens
  linkedin.py    OAuth e Posts API oficial
  xcentral.py    Central de Publicações do X
  reports.py     relatórios, PDF e CSV
  scheduler.py   rotinas automáticas sem duplicidade
  pipeline.py    ciclo diário do AGENTE HORIZONTE
  app.py         servidor do painel e API
  tray.py        ícone na bandeja do Windows
  assets/        ícone do HORIZONTE
  web/           painel (HTML, CSS e JS)
backup/          versão antiga do Horizonte e diagnóstico
tests/           testes automatizados
```
