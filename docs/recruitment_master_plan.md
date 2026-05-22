# Recruitment — Master Plan (Stages-first edition)

> **Дата:** 2026-05-19
> **Статус:** ready to execute після відповіді на 2 blocker-питання (§9.1)
> **Аудиторія:** AI-агент-виконавець + людина-рев'юер. План написаний так,
> щоб AI міг його імплементувати end-to-end, а людина — за 10 хвилин
> зрозуміти, що, коли і чому.
> **Версія:** v2 — синтез 4-експертного консиліуму
> (data-model architect, UX designer, migration/safety reviewer,
> implementation roadmap reviewer). Замінює § PR-послідовності в
> [`recruitment_ux_redesign_PLAN.md`](./recruitment_ux_redesign_PLAN.md);
> решта v1 (масштаб полів, 8-block layout, references) лишається валідною.

---

## 0. Що змінилось у v2 порівняно з v1

| Зміна | Причина | Звідки |
|---|---|---|
| **PR 1 розбито на PR 1a (BUG-fix) + PR 1b (foundation)** | PR 1a закриває user-visible баг за ½ дня, не чекаючи L-task. | Roadmap reviewer |
| **PR 1b і PR 2 мерджаться atomic-bundle-ом** | Без цього `_manage_test_task_stages` у hr_recruitment_test_task пише в `stage.template_id` глобально і перетирає config. R1, R3, R14. | Migration reviewer |
| **PR 4 (test task description per job) ↔ PR 5 (call stage) міняються місцями** | Test task per job — більший recruiter-pain зараз; call stage має зовнішню залежність (`appointment.type`) і вищий ризик. | Roadmap reviewer |
| **PR 6 (form restructure) лишається останнім** | XPath-конфлікти між 6 модулями краще робити **один раз** після стабілізації полів. | Roadmap reviewer |
| **Tab order у формі вакансії змінено**: Stages підіймається з 6-го на 2-е місце | Це core value цього редизайну; рекрутер не повинен клікати 5 вкладок щоб до неї дійти. | UX designer |
| **Hidden stages: 4 точки входу → 2 (+1 фільтр)** | Tab section (primary) + kanban banner; адмін-колонку в Configuration → Stages відкладаємо до клієнт-попиту. | UX designer |
| **6 нових полів на `hr.job.stage.config`** | fold, color, legend_*, requirements, external_id_mapping, sequence index. Деякі — на майбутнє, але резервуємо у міграції. | Data-model architect |
| **3 showstopper-фікси додано до PR 1b** | `_compute_stage` override, source-of-truth для template, sequence preservation у `_read_group_stage_ids`. | Migration reviewer |
| **IQ Test → Cognitive Test rename — fold-in у PR 1b migration** | Якщо чіпаємо stage-дані — зробити обидва переміщення разом, не двома міграціями. | Roadmap reviewer |

---

## 1. Companion docs (НЕ дублювати їх — посилайся)

| Файл | Що в ньому | Авторитет |
|---|---|---|
| [`recruitment_test_task_iq_stages_fix_plan.md`](./recruitment_test_task_iq_stages_fix_plan.md) | Аналіз і план фіксу для `add_test_task`/`add_iq_test` → стейджі приховані; нейминг IQ/Cognitive | Authoritative для **інваріанти** «галочка → стейджі видимі автоматично» та правила backend `iq_*` / frontend `Cognitive Assessment`. |
| [`recruitment_vacancy_stages_flow.md`](./recruitment_vacancy_stages_flow.md) | Root cause stages-бага, edge-case table (17 рядків), § «PR breakdown» v1 | Authoritative для **архітектури моделі** і edge-cases. PR-послідовність — застаріла, див. §3 цього доку. |
| [`recruitment_fields_for_ux_redesign.md`](./recruitment_fields_for_ux_redesign.md) | Каталог існуючих + запланованих полів `hr.job`, `hr.job.stage.config`, `hr.recruitment.stage`, `hr.applicant` | Authoritative для **полів**. Список нових полів від консиліуму — у §2.3. |
| [`recruitment_ux_redesign_PLAN.md`](./recruitment_ux_redesign_PLAN.md) | v1 master plan: 8-block layout, PR-послідовність, open questions | UX-grouping (§4-§6) і open questions (§10) — лишаються. Tab order і PR sequence — **superseded** цим доком. |
| [`data_safety_and_migration.md`](./data_safety_and_migration.md) | Гарантії additive-only міграції, 4 рівні захисту, чеклист передпрод | Authoritative для **migration safety**. Додатковий чеклист — у §6.5 цього доку. |
| [`/home/coder/src/odoo/jito_modules/CLAUDE.md`](../CLAUDE.md) | Правила репо: тільки `jito_modules/`, Odoo 17 only, tree not list, bump versions, README у кожному модулі | Не обговорюється. |

---

## 2. Архітектура (locked-in, з консиліум-правками)

### 2.1. Through-model — як було

```
hr.recruitment.stage   (global catalog; gets new `scope` Selection)
        ▲
        │ stage_id
        │
hr.job.stage.config    (through-model, payload edge of job × stage)
        │
        │ job_id
        ▼
hr.job                 (One2many stage_config_ids)
```

### 2.2. Доповнення від консиліуму

1. **`_order = 'sequence, stage_id'`** на `hr.job.stage.config` — обов'язково. Інакше tree-tab сортує нестабільно.
2. **`_inverse_scope` semantics** на `hr.recruitment.stage` явно зафіксовані:
   - `scope='global'` → `job_ids = [(5,0,0)]` + видалити config-рядки, де **усі** payload-поля (`mail_template_id, test_task_description, booking_link_id, requirements, color, fold`) `IS NULL` (тобто auto-rows). Override-рядки (з payload) **лишаємо** як «hidden global» — користувач сам вирішує що з ними робити.
   - `scope='specific'` → `job_ids` має містити principal-jobs; для кожного — гарантуємо config-рядок (idempotent create).
3. **Single source of truth для template після міграції** — `config.mail_template_id`. Computed `effective_mail_template_id` (related-fallback) на config readme-вом для view і `_track_template`. `stage.template_id` лишається як **fallback по замовчуванню для нових (job, stage) пар** і нічого більше.
4. **`_read_group_stage_ids` override** — обов'язково зберігає:
   - **`order`** з аргументу методу (передаємо в `_search(...)`);
   - **`'|', ('id','in', stages.ids)] + search_domain`** — поточні стадії grouped applicants завжди показуються, навіть якщо стали прихованими (інакше applicant «зникає»);
   - **`access_rights_uid=SUPERUSER_ID`** — щоб interviewer-роль не втратила колонки;
   - **Single SQL** замість двох search-ів — `OR`-domain із `scope='specific' AND id IN visible_config_ids` ∪ `scope='global' AND id NOT IN hidden_global_ids`.
5. **`_compute_stage` override** (новий, не був у v1) — стандартний шукає `fold=False`, не знає про `config.visible=False`. Треба фільтрувати: при створенні applicant'а на job дефолтна стадія = перша видима за порядком. **Інакше новий кандидат може лягти на сховану стадію і зникнути з kanban.**
6. **`_track_template` override** — обчислюємо template **eagerly** усередині overrideу і повертаємо dict `{field: (mail.template recordset, kwargs)}`. НЕ передаємо callable — Odoo 17 API цього не приймає. Кешуємо config-lookup у dict якщо batch.

### 2.3. Поля `hr.job.stage.config` — повний фінальний список

| Поле | Тип | Обов'язково в PR 1b? | Призначення |
|---|---|---|---|
| `job_id` | M2O `hr.job`, required, ondelete=cascade | ✅ | Батько |
| `stage_id` | M2O `hr.recruitment.stage`, required, ondelete=cascade | ✅ | Стадія |
| `sequence` | Integer, `index=True`, default=10 | ✅ | Порядок у tree-tab job (drag-handle) |
| `visible` | Boolean, default=True | ✅ | Колонка у kanban applicants |
| `mail_template_id` | M2O `mail.template` | ✅ | Per-job email override |
| `effective_mail_template_id` | M2O (computed) | ✅ | `mail_template_id or stage_id.template_id` — для рендеру |
| `test_task_description` | Html | ⚠️ Reserved (used in PR 4) | Per-job test-task body |
| `link_ids` | One2many → `hr.job.stage.config.link` | ⚠️ Reserved (used in PR 4) | Per-(job × stage) набір named-URL (git repo, specification, sample data) для рендеру у email-шаблоні та applicant-формі. Net-new — НЕ замінює `hr_recruitment_test_task.get_test_task_url()` (submission portal). |
| `booking_link_id` | M2O `calendar.appointment.type` | ⚠️ Reserved (used in PR 5) | Call stage |
| `booking_link_url` | Char | ⚠️ Reserved (used in PR 5) | Calendly/generic URL fallback |
| `fold` | Boolean, default=False | 🆕 PR 3+ | Per-job fold (інакше fold глобальний) |
| `color` | Integer | 🆕 PR 3+ | Per-job kanban column color |
| `legend_normal` | Char | 🆕 PR 3+ | Per-job kanban-state label (override stage) |
| `legend_blocked` | Char | 🆕 PR 3+ | Per-job kanban-state label |
| `legend_done` | Char | 🆕 PR 3+ | Per-job kanban-state label |
| `requirements` | Text | 🆕 PR 3+ | Per-job tooltip-вимоги |
| `external_id_mapping` | Char, `index=True` | 🆕 reserve | Для майбутньої Genio ATS sync — створюємо у PR 1b, лишаємо порожнім |
| `display_stage_name` | Char (computed, related) | 🆕 PR 1b | Для tree-в'ю без join |

`UNIQUE(job_id, stage_id)` — лишається. `_check_company_consistency` constraint: якщо `mail_template_id.company_id` set, повинна збігатись із `job_id.company_id`.

### 2.4. Поля `hr.recruitment.stage` — нові

| Поле | Тип | PR | Призначення |
|---|---|---|---|
| `scope` | Selection(`global`/`specific`), `compute=`, `store=True`, `inverse=` | PR 1b | Перемикач у формі + дефолт з контексту створення |

### 2.5. Нова child-модель `hr.job.stage.config.link`

Окрема через-модель для **per-(job × stage) named-URL** (git repo з ТЗ,
Notion-спека, sample data, etc.). Резервується у PR 1b, активно
використовується у PR 4. **Орогональна** до існуючого
`hr_recruitment_test_task.get_test_task_url()` (submission portal per
applicant) — нічого там не рефакториться.

| Поле | Тип | Призначення |
|---|---|---|
| `config_id` | M2O `hr.job.stage.config`, required, ondelete=cascade | Батько |
| `sequence` | Integer, default=10 | Порядок у tree-list, drag-handle |
| `label` | Char, required | Людино-читана назва ("Git repo", "Specification", "Submission form") |
| `url` | Char, required | URL; валідація regex `^https?://...` |

`_order = 'sequence, id'`. Жодних SQL-constraint (дублікати label
allowed — рекрутер сам вирішує).

### 2.6. Нове поле на `hr.job` — feature toggle

| Поле | Тип | PR | Призначення |
|---|---|---|---|
| `use_per_job_test_task_links` | Boolean, default=False | PR 1b (reserved) / PR 4 (UI+email) | Глобальний toggle на вакансії: вмикає UI секцію link-ів на вкладці Stages, активує рендер у mail.template і applicant form. Якщо `False` — link_ids ховаються з UI, email-плейсхолдер рендерить порожнечу. |

---

## 3. Roadmap — 7 PR в 4 фази

### Фаза 0 — BUG-fix sprint (½ дня)

#### PR 1a — `default_get` quick-fix

**Сcope:** мінімальний новий модуль `jito_modules/hr_recruitment_stage_default_fix/` (~80 LOC).

**Що робить:**
- Override `hr.recruitment.stage.default_get`: НЕ викидає `default_job_id` з контексту, пре-заповнює `job_ids=[(6,0,[default_job_id])]`.
- Жодних нових моделей, жодної міграції.

**Файли:**
```
hr_recruitment_stage_default_fix/
├── __manifest__.py            (depends=['hr_recruitment'], version 17.0.1.0.0)
├── __init__.py
├── README.md
├── models/__init__.py
├── models/hr_recruitment_stage.py   (override default_get)
└── tests/test_default_get.py
```

**Acceptance:**
- Створення стадії через «+ Stage» у kanban вакансії → стадія `job_ids=[поточна_вакансія]` (а не порожнє).
- Створення стадії з Configuration → Recruitment → Stages → `job_ids=[]` (глобальна).
- Існуючі стадії — без змін.

**Estimation:** S (½ дня) · **Незалежний від решти PR-ів; може бути deploy сьогодні.**

---

### Фаза 1 — Stages foundation (atomic bundle, PR 1b + PR 2)

> **Чому atomic:** consilium R1 + R3 + R14 — `_manage_test_task_stages`
> у `hr_recruitment_test_task` пише в `stage.template_id` глобально на
> кожному WRITE до job. Якщо PR 1b ставиться без PR 2 refactor, то будь-яка
> зміна вакансії у вікні «PR 1b deployed, PR 2 не deployed» перетирає
> config-стан. **Не deploy-ити їх окремо.** Можна мерджити окремими PR-ами,
> але release window — один.

#### PR 1b — `hr.job.stage.config` foundation

**Scope:** новий модуль `jito_modules/hr_recruitment_job_stage_config/`.

**Структура:**
```
hr_recruitment_job_stage_config/
├── __manifest__.py            (depends=['hr_recruitment','mail'], version 17.0.1.0.0)
├── __init__.py
├── README.md
├── models/
│   ├── __init__.py
│   ├── hr_recruitment_stage.py     # scope + default_get (replaces PR 1a)
│   ├── hr_job.py                   # stage_config_ids One2many, hidden_stage_count
│   ├── hr_applicant.py             # _read_group_stage_ids + _compute_stage + _track_template
│   └── hr_job_stage_config.py      # through-model з усіма полями з §2.3
├── views/
│   ├── hr_recruitment_stage_views.xml   # scope switcher + conditional job_ids
│   └── hr_job_views.xml                 # вкладка Stages (мінімальна — 4 колонки)
├── security/ir.model.access.csv
├── migrations/17.0.1.0.0/
│   ├── pre-migrate.py     # snapshot (applicant_id, stage_id) → tmp table
│   └── post-migrate.py    # backfill config rows + scope compute + IQ→Cognitive rename + diff snapshot
└── tests/
    ├── __init__.py
    ├── test_stage_scope.py
    ├── test_kanban_filtering.py
    ├── test_compute_stage_with_hidden.py    # consilium R10
    ├── test_template_fallback.py
    ├── test_migration_idempotent.py
    ├── test_migration_multi_company.py      # consilium R6
    ├── test_migration_zero_stages.py
    └── test_concurrent_sequence_update.py
```

**Що робить PR 1b (понад v1):**
- Усі 6 fix-ів з §2.2 (order, inverse_scope, source-of-truth template, `_read_group_stage_ids` повний, `_compute_stage` override, eager template resolution).
- Усі 7 reserved fields з §2.3 — створюються у міграції, лишаються порожніми/default.
- Pre-migrate snapshot applicant×stage_id; post-migrate diff → `ir.logging`. Гарантує R2.
- IQ Test → Cognitive Test rename бек-fold у міграції (open Q #5).
- `_check_company_consistency` constraint.

**Acceptance:**
- Старі вакансії відкриваються — kanban виглядає ідентично.
- «+ Stage» у kanban вакансії → стадія `scope='specific'`, `job_ids=[поточна_вакансія]`.
- Вкладка Stages існує, editable tree з 4 колонками (Drag | Seq | Stage | Visible | Email summary), accordion-row на ⋯ показує template picker.
- Усі existing tests у залежних модулях проходять.
- Multi-company canary не блимає cross-company template references.

**Estimation:** L (5–7 днів).

#### PR 2 — Email templates per job + test_task refactor

**Scope:**
- `models/hr_applicant.py` (у `hr_recruitment_job_stage_config`): `_track_template` override з fallback chain `effective_mail_template_id`.
- **Refactor `jito_modules/hr_recruitment_test_task/models/hr_job.py`**: `_manage_test_task_stages` більше НЕ пише `stage.template_id`; натомість створює/оновлює `hr.job.stage.config` рядок з `mail_template_id=mail_template_test_task_invite`. Видаляє `# CRITICAL FIX` хак.
- Bump `hr_recruitment_test_task` version.
- Тести: `test_template_fallback.py`, `test_test_task_refactor_writes_to_config.py`.

**Transition-window guard:** обидва PR (1b + 2) у одному merge-train. Якщо CI на 2 червоний — відкатити 1b теж.

**Acceptance:**
- Applicant переходить у Test Task → email рендериться з config.mail_template_id; якщо config рядка немає — fallback на stage.template_id; немає — нічого не шлемо.
- `_manage_test_task_stages` НЕ пише `stage.template_id` (assertion у тесті).

**Estimation:** M (2–3 дні).

---

### Фаза 2 — Stages UX (PR 3 ∥ PR 4)

> Ці два PR залежать **тільки** від Фази 1; не залежать один від одного.
> Можна писати паралельно різними агентами/розробниками.

#### PR 3 — Hide stages per job

**Scope:**
- Wizard `wizard/stage_hide_wizard.py(.xml)`: при `visible=False` на config-рядку, де є applicants у стадії → wizard з 3 опціями (move / hide anyway / cancel).
- Kanban toolbar banner `<i class="fa fa-eye-slash"/> {N} stages hidden in this job · [Manage stages →]` — `text-secondary` стиль, **passive**, тільки коли N>0, тільки на applicant kanban з default_job_id у контексті.
- Вкладка Stages: collapsible група «Hidden stages (N)» нижче основного дерева (consilium UX рекомендує — primary entry point).
- Applicant kanban search bar: чекбокс «Include hidden stages» (мінімалістично).
- **Без** окремої колонки в Configuration → Stages (UX recommend defer).
- `hidden_stage_count` computed на `hr.job`.
- Server-action audit script `scripts/find_stage_automations.py` (run on staging before deploy) — попередження адміну про base.automation з тригером на стадії.

**Acceptance:**
- Toggle Visible на config-рядку без applicants → миттєво, без модалу.
- Toggle Visible з applicants → wizard, опція «move» атомарно переносить, опція «hide anyway» — лишає applicants on hidden stage.
- Hidden stage остається доступна через 3 точки: tab section, kanban banner, applicant search filter.
- `_compute_stage` ніколи не дає новому applicant'у hidden стадію.

**Estimation:** M (3–4 дні).

#### PR 4 — Test task description + named-URL links per job (промоутед із позиції 5 у v1)

**Scope:**
- View (job form, вкладка Stages, accordion-row на config-рядку):
  - HTML-редактор `test_task_description`.
  - Editable inline list (`link_ids`) — колонки: drag | label | url. «Add a link».
  - Інші переключені поля — `mail_template_id` picker, `booking_link_id`.
- View (job form, header або біля поля test-task fields): toggle `use_per_job_test_task_links` Boolean. Коли `False` → секція link-ів прихована `attrs="{'invisible': [...]}"`.
- View (`hr.applicant` form): додаткова секція «Test task resources» з clickable списком link-ів. Visible only when:
  - `applicant.job_id.use_per_job_test_task_links == True`
  - applicant у стадії, де `config.link_ids` непорожній.
- **Refactor `jito_modules/hr_recruitment_test_task/`** (вдруге після PR 2):
  - При генерації test-task email — читає `hr.job.stage.config.test_task_description` для applicant'а job та current stage.
  - `html_is_empty()` helper для перевірки порожнього (`<p><br></p>` не є empty з view-perspective, але є з UX) — fallback на default.
  - **НЕ чіпає `get_test_task_url()`** (submission portal) — це ортогональна логіка.
- Email-template приклад (рендер у `mail_template_test_task_invite` або per-job override):
  ```jinja
  {% if object.job_id.use_per_job_test_task_links %}
    <p>Useful links for this task:</p>
    <ul>
    {% for link in stage_config.link_ids %}
      <li><a href="{{ link.url }}">{{ link.label }}</a></li>
    {% endfor %}
    </ul>
  {% endif %}
  ```
  `stage_config` resolve-ається через helper на `hr.applicant`, що тягне `(job_id, stage_id) → hr.job.stage.config`.
- URL validation: Python constraint regex `^https?://` на `hr.job.stage.config.link.url`. Inline-помилка у tree-list.
- Тести:
  - `test_test_task_per_job.py` — різні описи для двох вакансій → різні email-и.
  - `test_html_empty_test_task_description.py` — `<p><br></p>` → fallback.
  - `test_test_task_links_render_in_email.py` — два link-и у двох різних вакансіях → email кожного кандидата містить свій набір.
  - `test_use_per_job_test_task_links_toggle.py` — toggle=False ховає секцію в applicant form і не рендерить у email.
  - `test_test_task_link_url_validation.py` — невалідний URL (`ftp://`, `javascript:`) → ValidationError.

**Acceptance:**
- Recruiter задає різні test-task описи і різні набори named-URL для двох різних вакансій — applicants отримують різні email-и з власними переліками link-ів.
- Порожнє `test_task_description` (`<p><br></p>`) → fallback на default behaviour.
- `use_per_job_test_task_links=False` → ні UI секції в applicant form, ні `<ul>` у email body (Jinja-loop skipped).
- `hr_recruitment_test_task.get_test_task_url()` (submission portal) працює ідентично pre-PR 4.

**Estimation:** M (3–4 дні; +½ дня vs v1 за рахунок child-моделі).

---

### Фаза 3 — Extensions (PR 5)

#### PR 5 — Call stage / booking link (sub-module)

**Scope:** новий `jito_modules/hr_recruitment_call_stage/`, depends=`hr_recruitment_job_stage_config`, **soft-depends на `appointment`** (через `_assert_can_uninstall` + manifest check):
- `models/hr_job_stage_config.py` extend: задіює `booking_link_id` (M2O `calendar.appointment.type`) і `booking_link_url` (Char) — **обидва**.
- View: колонка Booking у accordion-row. Resolve at render: `config.booking_link_id.url or config.booking_link_url`.
- Email template context: `{{ stage_config.booking_link_id.url }}` / `{{ stage_config.booking_link_url }}`.
- `appointment_hr_recruitment` уже існує в Enterprise — перевіримо колізії.
- Тести: `test_call_stage_with_appointment_type.py`, `test_call_stage_with_url_fallback.py`.

**Acceptance:**
- Якщо `appointment` модуль активний → M2O picker працює.
- Якщо ні → Char URL fallback працює.
- Email рендериться з правильним URL.

**Estimation:** M (2–3 дні).

---

### Фаза 4 — UX redesign (PR 6, LAST)

#### PR 6 — `hr.job` form restructure

**Scope:** view-only PR в окремому модулі `jito_modules/hr_recruitment_job_form_redesign/` (depends на усі 6 sibling-модулів). Жодних model-змін.

**Tab order (фінальний, після UX critique):**
1. **Identity** — name, recruiter, manager, dept, company, location, contract type, tags, color, kanban_state
2. **Stages 🆕** — `stage_config_ids` editable tree + Hidden stages section
3. **Description** — description Html + AI JD-extract panel (collapsible) + requirement_statement_ids + weights
4. **Application form** — use_forms + form_template_id + question_line_ids (з inheritance бейджами)
5. **Public page** — use_published_config + published_*, website_published, process_*
6. **Headcount & timing** — no_of_recruitment, expected_employees, date_from/to, state
7. **AI & bulk** — cv_attachment_ids drop-zone, bulk progress, ai_match_mode, run_ai_*_on_bulk
8. **Tracking & sources** — tracker_ids (smart-button)

**Editable tree у вкладці Stages — 5 видимих колонок:** Drag | Seq | Stage | Visible (switch) | Email (summary text + popover) | ⋯ Actions.

Поля `test_task_description`, `booking_link`, `mail_template_id` picker, override `requirements` — в **accordion-row**, що розгортається по chevron у крайньому правому.

**Micro-interactions (з UX critique, 11 шт.):**
1. Toast on stage hide з [Undo] 5s.
2. Optimistic UI on visible toggle.
3. Drag-handle 50% opacity normal, 100% on hover, 44×44px touch hit-target.
4. Accordion expand 200ms ease-out, height-only.
5. Scope banner на старих global stages з [Convert to job-specific…] wizard.
6. AI panel 3-state copy (idle / processing / done з countdown).
7. Form template inheritance badges (Inherited / Modified / Custom).
8. Booking link [👁 Preview] mini-button.
9. Hidden stage row hover → inline [Show again].
10. Drag reorder тихо post chatter «moved from #20 to #10».
11. Mobile <768px: Stages tree колапсує до cards stack.

**Cross-module xpath audit (consilium R3):**
- Перед PR 6 — `grep -r "xpath" jito_modules/*/views/` по всіх sibling-модулях; перевірити `position="replace"/"after"/"before"` на той самий node.
- Integration test `test_form_loads_with_all_modules.py`: завантажити форму з усіма 6 sibling-модулями активованими — assert не падає.
- Використовувати semantic xpath (`//page[@name='...']`) замість positional.

**Acceptance:**
- Усі поля з [`recruitment_fields_for_ux_redesign.md`](./recruitment_fields_for_ux_redesign.md) досяжні з нової форми.
- Інтеграційний тест на 6 модулях — зелений.
- Performance: відкриття форми не повільніше базової >10%.
- Mobile breakpoint працює.

**Estimation:** L (5–7 днів).

---

## 4. Граф залежностей

```
PR 1a (default_get fix) ──► ships standalone, Day 1
        │
        ▼ (PR 1b extends/replaces 1a)
PR 1b (foundation) ─────┐
                        │
PR 2 (mail per job) ────┤  ATOMIC BUNDLE — one release window
                        │
        ┌───────────────┘
        │
        ├──► PR 3 (hide stages)      ┐
        │                             │  paralelizable
        ├──► PR 4 (test task per job) ┤  (different devs/agents)
        │                             │
        └──► PR 5 (call stage)        ┘
                │
                ▼
        PR 6 (form restructure) ───► merges all
```

**Single-threaded:** ~5–7 тижнів. **Parallel (PR 3 ∥ PR 4 ∥ PR 5):** 3.5–4.5 тижні.

---

## 5. Risk register (top-5, з 15 identified)

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| **R1** | `_manage_test_task_stages` race з config writes (PR 1b/2 window) | Critical | Atomic bundle PR 1b+2; CI guard «assert no stage.template_id write outside hr_recruitment_test_task migration». |
| **R10** | `_compute_stage` не знає про `visible=False` → applicant зникає | Critical | Override у PR 1b з тестом `test_compute_stage_with_hidden_stages.py`. |
| **R14** | Fresh install order: `hr_recruitment_test_task` ставиться після `hr_recruitment_job_stage_config` | Critical | `hr_recruitment_test_task` `depends=[hr_recruitment_job_stage_config]` після PR 2 refactor. |
| **R3** | Kanban N+1 у `_read_group_stage_ids` на job з багатьма стадіями | High | Single SQL з OR-domain; perf test fixture 50 jobs × 30 stages. |
| **R5** | View-extension конфлікти між 6 sibling-модулями у PR 6 | High | Semantic xpath; integration test `test_form_loads_with_all_modules.py`. |

Повна таблиця 15 ризиків — в Appendix A.

---

## 6. Cross-cutting (для всіх PR)

### 6.1. Backward compat
Кожен PR залишає older DB bootable. Міграції idempotent (re-runnable). `search_count` guard на дублях + log в `ir.logging` з module-version tag.

### 6.2. Performance
- `_read_group_stage_ids` — single SQL, prefetch `stage_id` через `_search` із `access_rights_uid=SUPERUSER_ID`.
- `_track_template` batch resolution (dict cache per recordset).
- Kanban-open benchmark: <10% regression на fixture 1000 applicants × 50 stages.

### 6.3. Multi-company
- `hr.recruitment.stage` лишається cross-company (як сток).
- `hr.job.stage.config` НЕ отримує `company_id` (через `job_id.company_id`).
- `_check_company_consistency` constraint: `mail_template_id.company_id` повинна бути compatible з `job_id.company_id` (NULL OK).

### 6.4. Logging
- Stage scope changes + visible toggles → `message_post` на stage I на job.
- Post-migrate → `ir.logging` з `level=INFO`, кожна (job, stage) пара.

### 6.5. Pre-prod checklist (additions to `data_safety_and_migration.md` §5)

- [ ] `pg_dump` BEFORE + AFTER; diff `hr_applicant`, `hr_recruitment_stage`, `hr_job` (data-only) → zero rows changed (R2 guarantee).
- [ ] `scripts/find_stage_template_writers.py` — grep по всіх installed модулях за `stage.template_id =`. Popup адміну зі списком (R3, R12).
- [ ] `scripts/find_stage_automations.py` — `ir.actions.server` + `base.automation` з моделлю `hr.recruitment.stage` чи фільтром на `stage_id`. Closes R13.
- [ ] Multi-company canary: вакансія у кожній компанії на staging.
- [ ] Rollback дrill: створити mail.template ПІСЛЯ install → uninstall → перевірити що template лишається без orphan-FK (R7).
- [ ] Advisory lock у Postgres під час post-migrate (R14 hardening).
- [ ] Performance regression на kanban-open <10%.

### 6.6. Hand-in artifacts per PR (доповнення до v1 §9)

Окрім summary/screenshots:
- **60–90s Loom-style screencast** на PR 1b, PR 3, PR 5 (інтерактивні UX-сценарії).
- **Performance benchmark report** на PR 1b (before/after `_read_group_stage_ids` timing).
- **Cross-module view-load smoke test log** на PR 6.
- **Migration dry-run log** на PR 1b (config rows count per job × stage).
- **i18n string audit** (`grep -L "_(" нові .py файли`).
- **A11y note** (tab-order у Stages tree, ARIA labels на kanban banner, contrast на muted hidden rows).
- **Rollback rehearsal evidence** на PR 1b (uninstall→reinstall лог на staging snapshot).

---

## 7. Testing strategy (binding)

Усі тести з v1 §8 лишаються. **Additions:**

| Тест | PR | Що покриває |
|---|---|---|
| `test_compute_stage_with_hidden_stages` | PR 1b | R10 (новий applicant не лягає на hidden стадію) |
| `test_migration_multi_company` | PR 1b | R6 (config-рядки не cross-leak між компаніями) |
| `test_migration_zero_stages` | PR 1b | Порожня компанія не падає |
| `test_migration_with_concurrent_test_task_install` | PR 2 | R14 (fresh install Кейс B) |
| `test_scope_recompute_on_upgrade` | PR 1b | R15 (stored compute після module upgrade) |
| `test_template_fallback_with_company_check` | PR 2 | R6 (cross-company template AccessError) |
| `test_rollback_with_orphan_templates` | PR 1b | R7 (uninstall з нестандартними templates) |
| `test_concurrent_sequence_update` | PR 1b | R9 (одночасне drag-reorder) |
| `test_html_empty_test_task_description` | PR 4 | R11 (`<p><br></p>` як empty) |
| `test_automated_action_compatibility` | PR 3 | R13 (`base.automation` на hidden stage) |
| `test_post_migrate_logs_to_ir_logging` | PR 1b | Audit log |
| `test_form_loads_with_all_modules` | PR 6 | R3 (view-extension конфлікти) |

CI command (binding):
```
odoo-bin -c <conf> -i hr_recruitment_job_stage_config,hr_recruitment_test_task,\
hr_recruitment_call_stage,hr_recruitment_job_form_redesign \
    --test-enable --stop-after-init --log-level=test
```

Repeat with `-u` на snapshot prod-like даних.

---

## 8. Estimation

| Фаза | PR | Size | Single-thread | Parallel |
|---|---|---|---|---|
| 0 | 1a | S | ½ день | — |
| 1 | 1b | L | 5–7 днів | — |
| 1 | 2 | M | 2–3 днів | — |
| 2 | 3 | M | 3–4 днів | ∥ PR 4, PR 5 |
| 2 | 4 | M | 2–3 днів | ∥ PR 3, PR 5 |
| 3 | 5 | M | 2–3 днів | ∥ PR 3, PR 4 |
| 4 | 6 | L | 5–7 днів | — |
| **Σ** | | | **20–30 днів** | **16–22 днів** |

Calendar: ~5–7 тижнів single-threaded, ~3.5–4.5 тижні parallel.

---

## 9. Open questions

### 9.1. Блокуючі для старту PR 1b

1. **Source of truth для `mail_template_id` після backfill міграції** — `stage.template_id` чи `config.mail_template_id`? Консиліум рекомендує **config як SoT, stage.template_id як fallback для нових пар**. **Підтвердити перед стартом.**
2. **`hired_stage` per-job — known limitation?** План v1 каже «лишається глобальним». Якщо реально потрібен per-job (різні «Hired»/«Onboarding»-стадії), це окремий PR після Фази 4. **Підтвердити чи цього достатньо як TODO.**

### 9.2. Не блокують PR 1b, але треба до Фази 2

3. **Groups на `scope='global'`** — обмежити toggle до `hr.group_hr_manager`? Default: leave open, додати `groups=` placeholder у view.
4. **Booking model для PR 5** — план каже dual-write (M2O + Char). Підтвердити чи рекрутери реально хочуть Calendly fallback, чи завжди буде appointment.type.

### 9.3. Не блокують взагалі (можна defer)

5. **Per-job `display_name`** на config — пропустити для Фази 1.
6. **Genio ATS sync** — defer; поле `external_id_mapping` зарезервовано.
7. **IQ → Cognitive rename** — fold-in у PR 1b міграцію (consilium recommend).

---

## 10. Де стартує AI-агент

1. Прочитати цей доку + 4 companion docs з §1.
2. Перевірити `odoo17_enterprise/odoo/addons/hr_recruitment/` для свіжих
   паттернів (`default_get`, `_read_group_stage_ids`, `_compute_stage`,
   `_track_template`).
3. Запитати у користувача відповіді на §9.1.1 і §9.1.2.
4. **Стартує з PR 1a** — у новій гілці, ~½ день, відправити на ревʼю
   окремо. Це швидка перемога і незалежна цінність.
5. Після злиття PR 1a → Скаффолд `hr_recruitment_job_stage_config/`
   за §2/§3, реалізувати PR 1b з усіма 12 тестами з §7.
6. PR 1b і PR 2 — у одному release-window. Не deploy 1b sole.
7. Hand-in per §6.6 + v1 §9.
8. Pause. Wait for user sign-off → start Фази 2.

---

## Appendix A — Повний risk register (15 рядків)

| # | Risk | Severity | PR | Mitigation |
|---|------|----------|----|-----------|
| R1 | `_manage_test_task_stages` race з config writes | Critical | 1b/2 | Atomic bundle, CI guard |
| R2 | Post-migrate непрямо змінює applicant.stage_id | High | 1b | Pre-migrate snapshot + diff |
| R3 | Kanban N+1 у `_read_group_stage_ids` | High | 1b | Single SQL, perf test |
| R4 | Idempotency drift (config.mail_template_id vs stage.template_id) | Medium | 1b | `effective_mail_template_id` computed |
| R5 | `scope` compute+store race conflict | High | 1b | `_inverse_scope` явно зафіксовано (§2.2) |
| R6 | Cross-company `mail_template_id` AccessError | Medium | 1b | `_check_company_consistency` |
| R7 | Rollback залишає orphan mail.templates | Low | 1b | Rollback drill (§6.5) |
| R8 | Test coverage gaps | High | all | 12 нових тестів (§7) |
| R9 | Concurrent sequence renumbering | Medium | 1b | `web_resequence` JSONRPC batch |
| R10 | `_compute_stage` не знає `visible` | Critical | 1b | Override з тестом |
| R11 | `<p><br></p>` як empty fail у PR 5 fallback | High | 4 | `html_is_empty()` helper |
| R12 | Pre_init_hook `hr_recruitment_test_task` чіпає XML-IDs | High | 2 | Sequence лагодимо у atomic bundle |
| R13 | Automated actions на hidden stage | High | 3 | `find_stage_automations.py` audit |
| R14 | Fresh install order Кейс B | Critical | 1b/2 | depends + advisory lock |
| R15 | Stored `scope` не recompute on upgrade | High | 1b | Явний recompute у post-migrate |

---

## Appendix B — Версія документа

- **v2** (2026-05-19) — consilium-revised: 6 PR-фаз, split PR 1, atomic 1b+2, reordered tabs, 6 нових полів, 12 додаткових тестів, 15-row risk register.
- **v1** ([`recruitment_ux_redesign_PLAN.md`](./recruitment_ux_redesign_PLAN.md))
  (2026-05-19 раніше того ж дня) — 6 PR, 8-block layout, 5 open questions.
