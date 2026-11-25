# Roadmap — Portage JobFinderOS sur OpenCode

Objectif : faire tourner JobFinderOS dans OpenCode (V2) sans casser l'installation Claude Code existante.
Principe : on **ajoute** la couche OpenCode à côté de `.claude/`, on ne déplace ni ne supprime rien d'origine.
Aucune donnée personnelle dans ce fichier ni dans la config (règle 1 d'AGENTS.md) ; les skills continuent de tout
lire depuis `config/profile.md`.

État des lieux (vérifié dans la doc OpenCode V2) :

| Composant Claude Code | OpenCode | Verdict |
|---|---|---|
| Scripts Python (`discover`, `scheduler_tick`, ATS poller, tests) | Aucune dépendance au harness | ✅ tel quel |
| `.claude/commands/*.md` (25 skills) | Découvert uniquement dans `.opencode/commands/` | ⚠️ à copier |
| `.claude/agents/*.md` (coach, scout, mark) | Découvert uniquement dans `.opencode/agents/` | ⚠️ à copier + frontmatter |
| `CLAUDE.md` (directives des agents) | Lu seulement s'il n'y a pas d'`AGENTS.md` au même niveau — la racine a un `AGENTS.md` | ⚠️ à brancher via `instructions` |
| Délégation `subagent_type:` (Agent tool) | Outil `subagent` (paramètre `agent`) | ⚠️ fallback déjà prévu dans les skills |
| Runner `claude -p /skill --allowedTools …` | `opencode run --format json --agent … --auto` | ⚠️ adapté (phase 4) |
| Connecteur Gmail claude.ai | Serveur MCP officiel Google configuré (phase 6), auth OAuth en attente du candidat | 🟡 configé, à authentifier |

---

## Avancement

| Phase | État |
|---|---|
| 1 — `opencode.json` | ✅ `instructions: ["CLAUDE.md"]` + permissions deny chargées (`opencode debug config`) |
| 2 — les 3 agents | ✅ `.opencode/agents/` : coach, scout, mark chargés avec `mode: all` et permissions dérivées (`opencode debug agents`) |
| 3 — les 25 skills | ✅ `.opencode/commands/` : `agent` + `subagent` dans le frontmatter, réécritures `.claude/` → `.opencode/` et `subagent_type` → `subagent`, tout chargé (`opencode api GET /api/command`) |
| 4 — runner | ✅ `JOBFINDEROS_HARNESS` (défaut `claude`), parseur NDJSON, `tests/fake_opencode.py`, 87 tests OK à l'époque (95 aujourd'hui), scheduler dry-run OK, smoke test réel `opencode run --agent scout` OK |
| 5 — durcissement | ✅ 17 denies shell + MCP, `tests/test_opencode_permissions.py` (5 tests), refus réel vérifié (`sendmail`, `git send-email`) |
| 6 — Gmail MCP | 🟡 serveur officiel Google configuré en lecture seule à 3 niveaux, tests OK ; auth OAuth en attente du candidat (projet GCP) |
| 7 — vérification finale | 🟡 tests / scheduler / `verify_local_automation.sh` / `.claude` OK ; run manuel bloqué (pas de `config/profile.md`) |

### Notes de terrain (phases 1 à 4)

- **`opencode run` n'expande pas les slash-commands** (vérifié : une commande de test est arrivée
  brute au modèle, qui est allé lire le fichier). Le runner envoie donc le corps du fichier de
  commande (frontmatter strippé) et sélectionne le persona avec `--agent` lu dans ce frontmatter.
- La sortie de `opencode run --format json` est du **NDJSON** (`step_start` / `tool_use` / `text` /
  `step_finish` / `error`). Échantillon réel enregistré : `tests/data/opencode_result_sample.ndjson`.
- **Modèle par défaut** : `opencode run` pointe sur OpenRouter dont le quota est insuffisant ici
  (HTTP 402, ~21k tokens disponibles alors que ~220k sont réservés). Toute vraie exécution
  planifiée devra passer par `JOBFINDEROS_OPENCODE_MODEL` (testé : `opencode/mimo-v2.6-flash-free`)
  ou par des crédits OpenRouter.
- **Portabilité Windows** : `cli_argv()` dans le runner et dans `jfgraph/llm.py` exécutent une
  cible `.py` via `sys.executable` (les fakes sans token des tests). Cela a corrigé un échec
  préexistant (`WinError 193`) qui mettait la suite à 12 échecs avant la phase 4.
- `verify_local_automation.sh` sort encore en 1 : aucune digest produite aujourd'hui sur cette
  machine (aucune run planifiée) — état d'environnement, pas une régression.
- Bruit préexistant sans échec : `tests/test_signals.py` imprime des `UnicodeDecodeError` (cp1252)
  dans un reader thread sous Windows.

### Notes de terrain (phase 5)

- `opencode.json` porte maintenant 17 règles `deny` : expéditeurs mail (`sendmail`, `Send-MailMessage`,
  `mailx`, `mutt`, `swaks`, `smtp`, `mailto:`), voies d'envoi API/git (`send-email`, `sendgrid`,
  `mailgun`, `nodemailer`), écritures repo (`git commit`, `git push`) et outils MCP
  dont le nom trahit un envoi (`*_send*`, `*_draft*`, `*_forward*`, `*_reply*`). La doc V2 confirme que
  les tools MCP sont adressés `<serveur>_<outil>` : la règle couvre donc un futur serveur Gmail sans
  connaître son nom.
- **Les règles d'agent sont ajoutées après les règles globales et le dernier match gagnant** (doc
  permissions V2) : un `effect: allow` large dans le frontmatter d'un `.opencode/agents/*.md`
  annulerait silencieusement tous les dénis. Les 3 frontmatters actuels ne portent que des `deny`
  (renforçants) ; un test (`test_no_broad_allow_override`) verrouille cet état.
- La politique de base d'OpenCode est `{ action: "*", resource: "*", effect: "allow" }` : sans deny, un
  envoi passe. Le deny est bien le verrou, pas le prompt.
- **Refus vérifié en vrai** (`opencode/mimo-v2.6-flash-free`, `--auto`) : `echo sendmail` puis
  `git send-email --help` → `{"error":"permission.rejected","message":"Permission denied: shell"}`.
  `--auto` n'outrepasse jamais une règle deny.
- `grep -niE "send|smtp|gmail|draft"` sur `.opencode/commands/` : aucune instruction d'envoi. Les
  occurrences sont des interdits (`Never sends`, `Never create_draft`) ou des checklists humaines
  (`Before you send`, cadence LinkedIn). Rien à corriger côté prompts.
- Faux positifs assumés : `*smtp*` et `*mailto:*` bloquent aussi des commandes inoffensives qui
  contiennent ces chaînes ; `*_reply*` peut masquer un tool MCP de lecture nommé `*_reply*`. Les
  skills n'en ont pas besoin.
- La couche deny reste un best-effort contre `python -c` / `sh -c` arbitraires (le scanner signale
  juste les commandes qu'il ne sait pas analyser) : la doctrine des agents demeure la première barrière.
- Cette machine a déjà un serveur MCP global `browse` (`~/.config/opencode/opencode.json`, tools `browse_*`) :
  il ne tombe sous aucun deny et c'est voulu (navigation web, aucun envoi). À garder en tête si un serveur
  Gmail est ajouté en phase 6.

### Vérification de parité (phase 3, refaite avant la clôture)

Comparaison `.claude/commands/` → `.opencode/commands/` corps à corps, frontmatter retiré :

- 25 fichiers de chaque côté, mêmes noms (aucun skill oublié ni renommé).
- `grep -r "\.claude/" .opencode/` → 0 occurrence : toutes les références pointent vers `.opencode/`.
- 12 fichiers divergent, mais uniquement par des réécritures mécaniques : 10 pour la délégation
  (`Agent tool` → « outil `subagent` », `subagent: "x"` → `agent: "x"`) et 2 pour le presse-papiers
  (`draft-message`, `voice-check` : `pbcopy` → « `pbcopy` sur macOS, `clip` sur Windows »).
- Aucun contenu de prompt perdu, aucune règle de doctrine modifiée → rien à rejouer dans `sim/` (règle 8).
- Agents (`coach`, `scout`, `mark`) : corps identiques à l'original, hors 3 réécritures mécaniques —
  « Claude Code » → « OpenCode », « Agent tool » → « outil `subagent` », et le presse-papiers rendu portable.
- `onboard.md` n'a pas de `agent:` **exprès** : c'est le guide de setup, il tourne dans la session principale
  (« Agent: none »), comme dans l'original. Les 24 autres skills sont bindées à un persona.
- `opencode debug config` après la phase 5 : les 17 règles et `instructions: ["CLAUDE.md"]` sont bien chargés,
  aucune règle rejetée silencieusement.

---

## Reste à faire

1. **Run manuel de bout en bout** (phase 7.4) : `/onboard` → `/jobs-scout` → `/jobs-daily` dans le TUI
   OpenCode, puis comparer le vault produit avec un run Claude Code. Nécessite `config/profile.md` et des réponses
   interactives — côté candidat.
2. **Authentification Gmail** (phase 6, dernière étape) : suivre les 4 étapes de la section « Phase 6 »
   ci-dessous (projet GCP + scope `gmail.readonly` seul, variables d'env, `opencode mcp auth gmail`).
   Tant que ce n'est pas fait, `/jobs-email` et la section inbox de `/jobs-digest` restent en
   dégradation implicite — les 4 skills concernés (`jobs-email`, `jobs-digest`, `day-of-card`,
   `email-watch`) appellent `search_threads` / `get_thread`, qui répondent `Unauthorized`.
3. **Commit du portage** : `.opencode/`, `opencode.json`, `tests/fake_opencode.py`,
   `tests/data/opencode_result_sample.ndjson`, `tests/test_opencode_permissions.py`, le runner et `roadmap.md`
   sont encore non suivis/modifiés. À faire sur demande explicite (règle 3 : jamais d'office).

---

## Phase 1 — Squelette de config (opencode.json)

Créer `opencode.json` à la racine :

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "instructions": ["CLAUDE.md"],
  "permissions": [
    { "action": "*", "resource": "*", "effect": "allow" },
    { "action": "shell", "resource": "*sendmail*", "effect": "deny" },
    { "action": "shell", "resource": "*mail *", "effect": "deny" }
  ]
}
```

- `instructions: ["CLAUDE.md"]` : **étape critique** — sans elle, OpenCode charge l'`AGENTS.md` de dev et ignore
  les directives des agents de recrutement (jamais d'envoi, warm-path-first, Recruiter's read…).
- Les permissions sont un premier verrou technique ; le verrou complet (déni sur tout outil d'envoi) est affiné en
  phase 5.
- Vérifier le chargement : `opencode debug config` et `opencode debug agents`.

**Livrable** : OpenCode démarre dans le repo avec `CLAUDE.md` effectivement chargé.

## Phase 2 — Les 3 agents

Copier `.claude/agents/{coach,scout,mark}.md` → `.opencode/agents/` avec cette traduction de frontmatter :

| Claude Code | OpenCode |
|---|---|
| `name: coach` | supprimé (l'ID vient du chemin : `coach`) |
| `description: …` | conservé tel quel |
| `model: inherit` | supprimé (inherit du parent par défaut) |
| — | ajouter `mode: subagent` (ils sont lancés en enfant, jamais primaires) |

Le corps (le prompt système) ne change pas d'une ligne.

- Vérifier : `opencode debug agents` liste `coach`, `scout`, `mark`.
- Les skills existants les appellent avec `subagent_type:` ; le fallback « si l'Agent tool est indisponible, lire le
  fichier de l'agent et exécuter en ligne » couvre le cas présent. La syntaxe OpenCode est corrigée en phase 3 pour
  les skills recopiés.

**Livrable** : un prompt du type « utilise le subagent coach » fonctionne dans le TUI.

## Phase 3 — Les 25 skills

Copier `.claude/commands/*.md` → `.opencode/commands/` (même nom de fichier = même nom de commande `/…`) :

- Frontmatter : garder `description` ; ajouter `agent: coach | scout | mark` pour que `/jobs-daily` s'exécute sous
  le bon agent (OpenCode supporte ce champ).
- Corps : `$ARGUMENTS` et `$1`, `$2` sont déjà compatibles — rien à changer.
- Corriger dans les copies les références à la syntaxe Claude Code :
  - `subagent_type: "mark"` → délegation `subagent` OpenCode (ou conserver la consigne de lecture inline du fichier
    d'agent, qui fonctionne déjà).
  - « Agent tool » → « outil subagent ».
- Ordre de recopie (par valeur d'usage) :
  1. `whats-next`, `jobs-daily`, `checkin` (quotidien)
  2. `jobs-scout`, `jobs-research`, `mark-pulse` (scan)
  3. `jobs-prep`, `mock-interview`, `day-of-card`, `jobs-cover`, `story` (entretiens)
  4. `warm-path`, `network-outreach`, `draft-message`, `voice-check` (avant candidature)
  5. `postmortem`, `profile`, `onboard` + le reste
- **Ne pas modifier les originaux `.claude/`** : les deux arborescents coexistent ; une divergence de prompt est un
  changement de comportement mesuré (règle 8) et devrait être reflété dans `sim/` si elle est adoptée.

**Livrable** : `/whats-next` et `/jobs-daily` répondent dans le TUI OpenCode.

## Phase 4 — Runner et scheduler (`opencode run`)

Adapter `scripts/jobfinderos_run_skill.py` (un seul entrypoint, règle 4) :

1. Sélecteur par variable d'env, p. ex. `JOBFINDEROS_HARNESS=claude|opencode` (défaut `claude` → régression nulle).
2. Chemin OpenCode : `opencode run --format json --agent <agent-du-skill> --auto "<prompt>"` avec les équivalents :
   - `--allowedTools` → permissions du projet (phase 1/5) ;
   - `--permission-mode acceptEdits` → règles `edit: allow` dans `opencode.json` ;
   - `--no-session-persistence` → `opencode run --archived`.
3. `record_result()` : prévoir un parseur pour la sortie JSON OpenCode (NDJSON) en plus du format actuel
   (`tests/data/claude_result_sample.json` fait foi pour Claude ; ajouter un échantillon OpenCode dans `tests/data/`).
4. Le chemin des skills : `.claude/commands/<skill>.md` doit basculer sur `.opencode/commands/<skill>.md` quand
   `JOBFINDEROS_HARNESS=opencode`.
5. Tests : étendre `tests/test_runner.py` pour le second harness, sans token (fake CLI déjà en place).

Le scheduler (`scheduler_tick.py`, `config/scheduler.yaml`, installateurs launchd / Task Scheduler) ne change pas :
il appelle le runner, qui change. Vérifier avec `python scripts/scheduler_tick.py --dry-run`.

**Livrable** : `python scripts/jobfinderos_run_skill.py jobs-daily jobs-daily` avec `JOBFINDEROS_HARNESS=opencode`
produit un run loggé dans `logs/` et `vault/Automation/`.

## Phase 5 — Durcissement « jamais d'envoi » ✅

Renforcer techniquement ce qui n'est que doctrine aujourd'hui :

- `opencode.json` : déni sur les outils/commands d'envoi (Gmail MCP, `sendmail`, `curl … smtp`, etc.) ; les drafts
  restent clipboard + vault. **Fait** : 11 patterns shell (7 mail + 4 voies API/git), 2 patterns git, 4 patterns MCP.
- Vérifier qu'aucun skill recopié ne comporte d'instruction d'envoi (grep sur `send`, `draft` dans
  `.opencode/commands/`). **Fait** : que des interdits et des checklists humaines.
- Après changement de permission : `python3 -m unittest discover -s tests -t .` et rejeu de `sim/` si un prompt de
  gate a bougé (règle 8). **Fait** : 91 tests OK ; aucun prompt de gate touché, donc `sim/` non rejoué.
- Ajout de `tests/test_opencode_permissions.py` (5 tests, sans token) pour qu'une règle deny supprimée par
  mégarde — ou un `allow` ajouté dans un frontmatter d'agent — fasse échouer la suite.

**Livrable** : une tentative d'envoi est refusée par OpenCode, pas seulement par le prompt. **Vérifié** :
`echo sendmail` refusé par le harness (`Permission denied: shell`, `executed:false`).

## Phase 6 — Gmail en MCP (config faite, auth côté candidat)

**Choix : le serveur MCP officiel de Google** (`https://gmailmcp.googleapis.com/mcp/v1`, remote,
OAuth géré par OpenCode) plutôt qu'un fork npm tiers — parce que ses tools s'appellent exactement
`search_threads` / `get_thread`, les noms que les skills utilisent déjà (parité Claude), et parce
qu'il **n'expose aucun tool d'envoi** (sa liste : `create_draft`, labels, trash… pas de `send`).

**Lecture seule à trois niveaux** (défense en profondeur) :

1. **Scope OAuth** : `oauth.scope` limité à `gmail.readonly` dans `opencode.json` → Google rejette
   toute mutation même si un verrou harness tombe.
2. **Deny global** `{ action: "gmail_*", effect: "deny" }` → tout tool gmail non listé est bloqué.
3. **Allowlist ordonnée** (dernier match gagnant) : `gmail_search_threads`, `gmail_get_thread`,
   `gmail_get_message` en *après* le deny — les seuls tools que les skills appellent.
   `create_draft` tombe aussi sous le déni existant `*_draft*`.

**Credentials hors du fichier** : `client_id` / `client_secret` sont des placeholders
`{env:GMAIL_MCP_CLIENT_ID}` / `{env:GMAIL_MCP_CLIENT_SECRET}` (config chargée sans les variables =
chaîne vide, comportement identique à avant, vérifié). `opencode.json` sera commité : jamais de secret
dedans (règle 1).

**Vérifications faites** : `opencode debug config` (tout charge) · `opencode mcp list` →
`✓ gmail connected` · catalogue Code Mode = exactement les 3 tools allowlistés · probe réel
`search_threads` (requête sans résultat) → `Unauthorized` = auth manquante, pas un défaut de config ·
`opencode run` réel → `RUNNER-OK` **avec** le serveur non authentifié (les runs planifiés ne cassent
pas) · 95 tests OK.

**Reste côté candidat (étapes Google, interactives)** :

1. Quick setup : developers.google.com/workspace/gmail/api/guides/configure-mcp-server — projet GCP,
   API `gmailmcp.googleapis.com`, écran de consentement avec le scope
   `https://www.googleapis.com/auth/gmail.readonly` (pas de `gmail.compose` / `gmail.modify`),
   client OAuth de type **Desktop**, compte ajouté en test user.
2. Exporter `GMAIL_MCP_CLIENT_ID` et `GMAIL_MCP_CLIENT_SECRET` (env, jamais dans le JSON).
3. `opencode mcp auth gmail` → consentement navigateur. Google ne supporte pas le dynamic client
   registration (erreur vérifiée : « does not support dynamic client registration ») : le client
   pré-enregistré est donc obligatoire.
4. Contrôler : un probe `search_threads` sans résultat doit renvoyer 0 résultat, plus `Unauthorized`.

Aucun skill à modifier : les noms d'outils correspondent déjà. `/jobs-email`, `/jobs-digest`,
`day-of-card` et `email-watch` passent d'une dégradation implicite à un vrai accès lecture.

## Phase 7 — Vérification finale

1. `python3 -m unittest discover -s tests -t .` (sans token). ✅ 95 tests OK (25/11/2026).
2. `python scripts/scheduler_tick.py --dry-run`. ✅ `weekly_due: true`, `daily_due: false`, priority-watch invoked.
3. `bash scripts/verify_local_automation.sh` (ou l'équivalent Windows). ⚠️ sort en 1, comme noté en phase 4 :
   aucune digest produite aujourd'hui sur cette machine (`vault/Daily Digests/2026-11-24.md` absente,
   `logs/scheduler-cron` absent). État d'environnement, pas une régression du portage.
4. Run complet manuel : `/onboard` → `/jobs-scout` → `/jobs-daily` dans le TUI OpenCode ; comparer le vault produit
   avec un run Claude Code de référence. ⛔ **Bloqué** : pas de `config/profile.md` sur cette machine (gitignoré, données
   personnelles) et `/onboard` est interactif. À faire par le candidat ; le smoke test `opencode run --agent scout`
   en conditions réelles (phase 4 et 5) tient lieu de preuve que le harness tourne.
5. Contrôler que `.claude/` est intact (le runner Claude continue de fonctionner) : c'est le critère « pas de
   régression ». ✅ `git status --short .claude/` vide, runner par défaut toujours `claude`.

---

## Hors périmètre (pour l'instant)

- Supprimer ou migrer `.claude/` (l'installation Claude Code reste supportée en parallèle).
- Automatiser l'envoi d'emails (interdit par doctrine, règle 3).
- Committer quoi que ce soit du vault ou du profil (gitignore inchangé).
- Repenser le découpage des skills : « keep skills thin » (règle 5) reste valable.

## Ordre résumé

```
Phase 1  opencode.json + instructions CLAUDE.md        (bloquant tout le reste)
Phase 2  .opencode/agents/ (3 fichiers)
Phase 3  .opencode/commands/ (25 fichiers)
Phase 4  runner opencode + tests
Phase 5  permissions durcies
Phase 6  Gmail MCP (optionnel)
Phase 7  vérification bout en bout
```
