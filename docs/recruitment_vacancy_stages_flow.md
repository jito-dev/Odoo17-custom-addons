# Recruitment — Vacancy creation flow & shared-stages issue

Документ пояснює поточну поведінку модуля рекрутменту в Odoo 17 щодо
створення вакансій (`hr.job`) і стадій рекрутменту (`hr.recruitment.stage`),
а також ЧОМУ стадії, які ви додаєте під одну вакансію, з’являються у всіх
інших вакансіях.

Файл навмисно тримаємо у `jito_modules/docs/`, щоб його легко знайти й
оновити, коли поведінку буде виправлено.

---

## 1. Як зараз створюється вакансія (Job)

Модель: `hr.job` (зі стандартного `hr_recruitment`, розширена в
`jito_modules/hr_recruitment_vacancy_page/` та
`jito_modules/hr_recruitment_extract_openai/`).

Базовий флоу:

1. Користувач відкриває застосунок **Recruitment**.
2. На головному екрані (kanban з картками вакансій) натискає **New**.
3. Створюється запис `hr.job` з мінімальними полями (назва, відділ,
   компанія, відповідальний тощо).
4. Після збереження вакансії на її картці видно лічильники кандидатів і
   кнопку для переходу до kanban-board кандидатів цієї вакансії.
5. Усередині board кандидатів конкретної вакансії користувач бачить
   колонки = стадії рекрутменту (`hr.recruitment.stage`) і може додати
   нову колонку через **+ Stage**.

Жодних кастомних змін у jito_modules для самого процесу створення
`hr.job` чи `hr.recruitment.stage` немає — флоу стоковий Odoo 17.

---

## 2. Модель `hr.recruitment.stage` — ключ до проблеми

Файл стоку:
`odoo17_enterprise/odoo/addons/hr_recruitment/models/hr_recruitment_stage.py`

Важливе поле:

```python
job_ids = fields.Many2many(
    'hr.job', string='Job Specific',
    help='Specific jobs that uses this stage. Other jobs will not use this stage.')
```

Семантика поля `job_ids` (Job Specific):

- `job_ids` **порожнє** → стадія **глобальна**, видима у **ВСІХ** вакансіях.
- `job_ids` містить конкретні вакансії → стадія видима **тільки** в них.

Тобто Odoo не зберігає окремий набір стадій «під кожну вакансію».
Існує єдина таблиця `hr.recruitment.stage`, а належність до вакансії
описується тільки через M2M `job_ids`.

---

## 3. Як фільтруються стадії в kanban кандидатів

Файл: `odoo17_enterprise/odoo/addons/hr_recruitment/models/hr_applicant.py`

```python
stage_id = fields.Many2one(
    'hr.recruitment.stage', 'Stage', ...,
    domain="['|', ('job_ids', '=', False), ('job_ids', '=', job_id)]",
    group_expand='_read_group_stage_ids')

def _read_group_stage_ids(self, stages, domain, order):
    job_id = self._context.get('default_job_id')
    search_domain = [('job_ids', '=', False)]
    if job_id:
        search_domain = ['|', ('job_ids', '=', job_id)] + search_domain
    ...
```

Що це означає на практиці:

- Якщо ви відкрили kanban кандидатів **конкретної вакансії**
  (у контексті є `default_job_id`), Odoo показує колонки = глобальні
  стадії + стадії, де `job_ids` містить цю вакансію.
- Якщо ви відкрили **загальний** kanban кандидатів (без `default_job_id`),
  показуються тільки **глобальні** стадії (`job_ids = False`).

Тому стадія, у якої `job_ids` порожнє, з’являється в kanban кожної
вакансії — це і є джерело проблеми, яку ви бачите.

---

## 4. Чому нова стадія стає «глобальною», навіть якщо ви її створили з конкретної вакансії

У тому ж файлі `hr_recruitment_stage.py`:

```python
@api.model
def default_get(self, fields):
    if self._context and self._context.get('default_job_id') \
            and not self._context.get('hr_recruitment_stage_mono', False):
        context = dict(self._context)
        context.pop('default_job_id')   # <— ключовий рядок
        self = self.with_context(context)
    return super(RecruitmentStage, self).default_get(fields)
```

Що тут робиться:

- Коли ви натискаєте **+ Stage** у kanban кандидатів вакансії,
  Odoo передає `default_job_id` у контексті.
- Очікувано це мало б автоматично додати поточну вакансію в `job_ids`
  нової стадії.
- Але `default_get` **викидає** `default_job_id` з контексту (якщо не
  встановлено `hr_recruitment_stage_mono=True`).
- Як результат, нова стадія створюється з **порожнім `job_ids`** →
  одразу стає глобальною → з’являється у всіх інших вакансіях.

Прапор `hr_recruitment_stage_mono` нігде в стандартному UI Odoo 17
не виставляється (`grep` по `hr_recruitment` дає лише цей рядок).
Тобто за замовчуванням ви завжди отримуєте «глобальну» поведінку.

Це — навмисне рішення Odoo (спрощує менеджмент пайплайнів у малих
компаніях), але для вашого юзкейсу воно сприймається як баг.

---

## 5. Поточний (тимчасовий) workaround для користувача

Щоб стадія була видима тільки в одній вакансії, потрібно вручну:

1. Відкрити запис стадії (Configuration → Recruitment → Stages, або
   через picker у формі стадії).
2. У полі **Job Specific** (`job_ids`) додати ту вакансію (або декілька),
   до яких стадія повинна належати.
3. Зберегти.

Після цього стадія перестане з’являтись у kanban інших вакансій.

---

## 6. Що саме треба виправити в коді (план виправлення)

Можливі варіанти — від найменш інвазивного до найбільш:

### Варіант A. Автопідставляти `default_job_id` у `job_ids` нової стадії

У `jito_modules` створити модуль (наприклад розширити
`hr_recruitment_vacancy_page` або новий невеликий модуль), і
переозначити `default_get` у `hr.recruitment.stage`:

- Не викидати `default_job_id` з контексту, а навпаки —
  попередньо заповнювати `job_ids = [(6, 0, [default_job_id])]`.

Плюси: мінімум коду, користувач отримує очікувану поведінку
«створив стадію всередині вакансії — стадія належить тільки їй».
Мінуси: змінює стандартну поведінку Odoo; треба не зламати випадок,
коли стадію свідомо створюють як глобальну з Configuration.

Відрізнити «створення з kanban вакансії» від «створення з Configuration»
якраз і можна за наявністю `default_job_id` у контексті.

### Варіант B. Запропонувати користувачу вибір при створенні

Додати поле-перемикач у форму стадії типу
«Зробити цю стадію глобальною / специфічною для вакансії», з
дефолтом «специфічна», якщо стадія створюється з контексту вакансії.

Плюси: явність і контроль.
Мінуси: трохи більше UI/UX роботи, треба перекладати, додавати в view.

### Варіант C. Повністю розв’язати стадії від глобального пулу

Зберігати стадії в окремій таблиці на кожну `hr.job`
(наприклад через `One2many job_stage_ids`), і використовувати їх
замість `hr.recruitment.stage`. Це найбільша і найризикованіша зміна,
вона ламає інтеграції/звіти і не рекомендована.

### Рекомендація

**Варіант A** як швидке виправлення + **Варіант B** як коректне довге
рішення з UI-перемикачем у формі стадії. Деталі реалізації узгодимо
окремо перед кодом.

---

## 7. Файли, які доведеться чіпати при виправленні

- Новий/існуючий модуль у `jito_modules/` (рекомендую окремий
  `hr_recruitment_job_specific_stages/`):
  - `models/hr_recruitment_stage.py` — `default_get` override.
  - (опціонально) `views/hr_recruitment_stage_views.xml` — додати
    helper-поле/перемикач.
  - `__manifest__.py`, `__init__.py`, `security/ir.model.access.csv`
    (якщо знадобиться).
- Документація модуля (`README.md` усередині модуля) — за вашими
  правилами з `CLAUDE.md`.

Стандартні файли в `odoo17_enterprise/` чіпати **не можна** (так
сказано в `CLAUDE.md`).

---

## 8. TL;DR

- Стадії рекрутменту в Odoo 17 — це один глобальний список
  `hr.recruitment.stage`.
- Належність стадії до конкретної вакансії описується M2M `job_ids`
  («Job Specific»).
- Якщо `job_ids` порожнє — стадія видима у ВСІХ вакансіях.
- Коли ви створюєте стадію з kanban вакансії, Odoo навмисно
  **викидає** `default_job_id` з контексту, тому `job_ids` лишається
  порожнім → стадія стає глобальною.
- Це не баг вашого коду — це поведінка стокового
  `hr_recruitment.stage.default_get`.
- Фікс: оверайд `default_get` у власному модулі в `jito_modules/`,
  щоб автоматично прив’язувати нову стадію до поточної вакансії.

---

# ПЛАН ВПРОВАДЖЕННЯ (Варіант B+, підготовлений як консиліум)

> Цей розділ — детальний імплементаційний план. Він враховує не лише
> поточну задачу (per-vacancy стадії), а й суміжні майбутні задачі:
> per-stage email template per job, call stage з booking link,
> test task description per stage per job, hiding stages per job,
> Genio ATS, перейменування IQ→Cognitive.
> Скликаний «консиліум» дивиться на задачу з чотирьох кутів:
> **(1) Data Model**, **(2) UX/Recruiter workflow**,
> **(3) Odoo conventions / forward-compat**, **(4) QA / edge-cases**.

## 0. Ключове рішення архітектури

**Не обмежуватись розширенням `job_ids` на `hr.recruitment.stage`.**
Натомість ввести нову модель «per-job per-stage конфігурація»:

```
hr.job.stage.config           (PK auto)
├── job_id            M2O hr.job        required, ondelete=cascade
├── stage_id          M2O hr.recruitment.stage  required, ondelete=cascade
├── sequence          Integer           (override порядку стадії в межах вакансії)
├── visible           Boolean (default True)   ← закриває таску "hide stage per job"
├── mail_template_id  M2O mail.template (nullable)  ← per-job override
├── test_task_description Html (nullable)            ← per-job test task body
├── booking_link_id   M2O calendar.appointment.type (nullable) ← call stage
└── _sql_constraints: UNIQUE(job_id, stage_id)
```

`hr.recruitment.stage` залишається глобальним каталогом, але отримує
прапор `scope`:

```
hr.recruitment.stage
├── scope = Selection([('global','Global'), ('specific','Specific jobs')])
│           default залежить від контексту створення (див. §2)
├── job_ids   (існуюче M2M — лишаємо для зворотної сумісності, але
│              стає авто-обчислюваним через job.stage.config)
└── template_id ... (fallback, коли в job.stage.config немає override)
```

**Чому саме так, а не просто розширення M2M:**

| Кут зору | Аргумент |
|---|---|
| Data Model | Per-job override email template, test task description, booking link, sequence, hidden — це 5 полів, які логічно живуть на ребрі `job × stage`. Класти їх на M2M не можна — M2M не має payload. |
| UX | Рекрутер у формі вакансії має одну вкладку «Stages» зі списком ребер job.stage.config, де редагує все по своїй вакансії, не торкаючись інших. |
| Odoo conventions | Це класичний pattern «through-model», як `sale.order.line` між order/product. Стабільно ORM-сумісно з `One2many` на обидва кінці. |
| QA | Видалення вакансії автоматично прибирає її конфіги (cascade); видалення стадії — теж. Поточні дані не ламаються — глобальні стадії читаються через fallback. |

## 1. Структура модулів

Створюємо **один новий модуль** у `jito_modules/`:

```
hr_recruitment_job_stage_config/
├── __manifest__.py
├── __init__.py
├── models/
│   ├── __init__.py
│   ├── hr_recruitment_stage.py     # scope, default_get override, _read_group
│   ├── hr_job.py                    # One2many stage_config_ids, helpers
│   ├── hr_applicant.py              # _read_group_stage_ids override, template fallback
│   └── hr_job_stage_config.py       # NEW THROUGH-MODEL
├── views/
│   ├── hr_recruitment_stage_views.xml
│   ├── hr_job_views.xml             # вкладка «Stages» з editable tree
│   └── hr_applicant_views.xml       # (мінімально, лише якщо треба)
├── wizard/
│   ├── stage_scope_change_wizard.py # підтвердження при scope change
│   └── stage_scope_change_wizard.xml
├── data/
│   └── ir_actions.xml               # action для відкриття form стадії з банером
├── security/
│   └── ir.model.access.csv
└── README.md                        # guidance per CLAUDE.md
```

**Залежності модуля:** `hr_recruitment`, `mail` (для template), і
м'яко-опційно — `calendar` (для booking_link_id; можна винести в окремий
sub-module якщо ускладнить залежності).

**Окремі модулі, які потім будуються поверх цього (далі по roadmap):**

- `hr_recruitment_call_stage` — додає логіку "call stage" + UI для
  booking_link. Залежить від `hr_recruitment_job_stage_config`.
- `hr_recruitment_test_task` — **рефакториться**, перестає писати в
  глобальний `stage.template_id`, переходить на `job.stage.config`.

## 2. UX дизайн (Recruiter workflow)

### 2.1. Створення стадії з kanban вакансії (+ Stage)

Дефолт: `scope='specific'`, `job_ids=[current_job]`. Це закриває
домовлений сценарій («рекрутер створив усередині вакансії — стадія
її»). Поведінка реалізується в `default_get`: НЕ викидаємо
`default_job_id` з контексту, а використовуємо його.

У формі стадії (inline-quick-create + повна форма) показуємо
**Scope-перемикач** (radio/Selection field):

- `Global` — видима у всіх вакансіях.
- `Specific jobs` — багатовибір вакансій (M2M widget). Дефолт у
  багатовиборі — поточна вакансія.

Перемикач — це і є «гібрид Global / Specific jobs» з відповіді.

### 2.2. Конфігурація стадій у формі вакансії

У `hr.job` form view додаємо вкладку **Stages** з editable tree:

| Sequence | Stage | Visible | Email Template | Test Task Description | Booking Link |
|---|---|---|---|---|---|
| 10 | Initial Qualification | ☑ | (default з стадії) | — | — |
| 20 | Test Task | ☑ | (override) | (per-job text) | — |
| 25 | Call | ☑ | (call template) | — | (booking type) |
| 30 | Contract | ☐ (hidden) | — | — | — |

«Visible» закриває таску «hide stage per job» — `_read_group_stage_ids`
фільтрує невидимі. Дозволяємо додавати глобальні та job-specific
стадії, перетягувати порядок.

Підтаска `Implement stage hiding functionality` з підтвердженням-попапом —
покриваємо кнопкою «Hide» у tree-рядку, яка викликає
`stage_scope_change_wizard` з текстом про вплив на наявних кандидатів.

### 2.5. Де видно приховані стадії і як їх повернути

Сховані стадії повинні бути **знайдені за 1 клік** з місць, де
рекрутер найчастіше:

**(a) Вкладка «Stages» у формі вакансії — головне місце.**
Tree-список показує **усі стадії, релевантні цій вакансії — і видимі,
і приховані**. Рядки приховаих стадій:

- мають значок 👁️‍🗨️ (eye-slash) у колонці Visible;
- візуально приглушені (`text-muted` / сірий фон);
- мають бейдж `Hidden` поряд із назвою;
- знизу tree-списку є **окрема секція-група «Hidden stages (N)»**
  (через `<group expand="0">`), яку можна згорнути/розгорнути.

Повернути стадію — просто перемкнути тогл Visible назад → `True`.

**(b) Kanban applicants — індикатор у toolbar.**
Над колонками kanban (у header вакансії) показуємо невелику
пасивну плашку:

```
🔒 3 stages hidden in this job  ·  Manage
```

Клік по «Manage» відкриває форму вакансії одразу на вкладці Stages,
прокручену до секції «Hidden stages». Якщо прихованих стадій 0 —
плашки немає взагалі (zero-noise UX).

**(c) Глобальне меню Configuration → Recruitment → Stages —**
адмінська точка. У tree-в'ю стадій додаємо колонку «Hidden in jobs»
(computed, показує count вакансій, де `visible=False`). Клік
відкриває форму стадії з вкладкою «Per-job configuration», де видно
матрицю job × visible — адмін може масово увімкнути стадію назад
у кількох вакансіях.

**(d) Search / filter на applicant kanban.**
Додаємо фільтр «Include hidden stages» (Search panel) — коли
ввімкнено, kanban показує колонки прихованих стадій з бейджем
`Hidden`. Це для випадку, коли кандидат лежить у прихованій стадії
і рекрутер хоче його швидко знайти, не йдучи в форму вакансії.

Усі чотири точки опційно посилаються на одну й ту саму action,
тож менеджмент логіки централізований.

### 2.3. UI-підказка на старих глобальних стадіях

У формі `hr.recruitment.stage` показуємо м'який банер
(`<div class="alert alert-info">`), якщо `scope='global'` І стадія
вже використовується кандидатами кількох вакансій:

> _"Ця стадія видима у всіх вакансіях. Хочете обмежити її конкретними
> вакансіями? [Convert to job-specific]"._

Кнопка відкриває wizard, де адмін обирає, до яких вакансій прив'язати
стадію (опційно — авто-розкидати по вакансіях, де вже є кандидати в
цій стадії).

### 2.4. Доступи

Поки лишаємо без жорстких прав (відповідь користувача — "поки не знаю").
Архітектурно готуємо `groups=` на полі `scope` так, щоб у наступній
ітерації легко обмежити Global-режим тільки `hr.group_hr_manager`,
без ламки міграції. Поле `visible` і per-job overrides — для будь-якого
recruiter.

## 3. Backend логіка

### 3.1. `hr.recruitment.stage`

- Додати `scope = Selection([...])` із `compute` за станом `job_ids`
  (writable, store=True). Це робить поле читабельним і пошукабельним,
  але не дублює стан.
- Override `default_get`: якщо `default_job_id` у контексті —
  встановити `scope='specific'`, `job_ids=[(6,0,[default_job_id])]`.
  НЕ викидаємо `default_job_id` з контексту як це робить ванільний Odoo.
- Hook у `write`/`create`: коли `scope` змінюється з `specific` → `global`
  або `job_ids` змінюється — синхронізувати `hr.job.stage.config`
  (створювати/прибирати рядки).

### 3.2. `hr.applicant`

- Override `_read_group_stage_ids`:
  ```python
  job_id = self._context.get('default_job_id')
  if job_id:
      # стадії, де config(visible=True) для цієї job
      configs = env['hr.job.stage.config'].search([
          ('job_id', '=', job_id), ('visible', '=', True)])
      stage_ids = configs.stage_id.ids
      # + global stages without explicit hide (немає config row АБО visible=True)
      global_stages = env['hr.recruitment.stage'].search([
          ('scope', '=', 'global')])
      hidden_globals = env['hr.job.stage.config'].search([
          ('job_id', '=', job_id),
          ('stage_id', 'in', global_stages.ids),
          ('visible', '=', False)]).stage_id.ids
      stage_ids += (global_stages.ids - hidden_globals)
      return stages.browse(set(stage_ids)).sorted(...)
  ```
- Override `_track_template`: замість `applicant.stage_id.template_id`
  використовувати **fallback chain**:
  1. `hr.job.stage.config` (job=applicant.job_id, stage=new stage).mail_template_id
  2. `stage.template_id` (глобальний default)
  3. None → no mail.

### 3.3. `hr.job.stage.config` (нова модель)

- Стандартний CRUD.
- Constraint: для `scope='specific'` стадії автоматично створюється
  config-рядок для кожного job у `job_ids`. Для `scope='global'`
  config-рядки створюються лише коли recruiter явно override-нув щось.
- Performance: індекс по `(job_id, stage_id)` уже є через UNIQUE.

### 3.4. Sequence та порядок стадій

У межах однієї вакансії сортування — по
`coalesce(config.sequence, stage.sequence)`. Це дозволяє per-job
переставляти стадії, не зачіпаючи інші вакансії.

## 4. Edge-cases та як їх обробляємо

| # | Edge-case | Поведінка |
|---|---|---|
| 1 | Зміна scope `global → specific` із виключенням вакансії, де є кандидати, АБО приховання стадії (`visible=False`) із кандидатами в ній | **Варіант 1 (обрано):** перед збереженням відкривається модальний wizard зі списком кандидатів у цій стадії. Опції: (a) **Перенести в іншу стадію** (dropdown із видимих стадій цієї вакансії) → `applicant.stage_id` оновлюється для всіх кандидатів пакетно, (b) **Все одно сховати** — `applicant.stage_id` НЕ міняється, кандидати лишаються «приховані» і доступні через UI з §2.5, (c) **Скасувати**. Кнопка «Все одно сховати» вимагає окремого підтвердження («Ви впевнені? Кандидати зникнуть з kanban цієї вакансії, але доступні в Hidden stages»). |
| 2 | Зміна scope `specific → global` | Дозволяємо одразу, лог у chatter стадії. |
| 3 | Видалення вакансії | `ondelete=cascade` на `hr.job.stage.config` чистить ребра. Стадії не чіпаються. |
| 4 | Видалення стадії | Стандартний Odoo restrict, якщо є кандидати. Інакше cascade на config. |
| 5 | `hired_stage=True` на стадії | Залишається глобальним прапором стадії. Якщо вакансія приховала hired-стадію — попередження «вакансія не має активної hired stage». |
| 6 | Перейменування стадії одним рекрутером — бачать усі | Не змінюємо. Якщо рекрутер хоче власну назву — створює нову specific-стадію. (Альтернатива: per-job display_name у config — додамо тільки якщо явно знадобиться, щоб не плодити поля.) |
| 7 | Дублікати назв стадій між вакансіями | Allowed. У звітах групувати по `stage_id`, не по name. |
| 8 | Mail template fallback порожній | Лог у chatter applicant без помилки. |
| 9 | Multi-company: job із company A, stage без company | Stage лишається cross-company. Якщо знадобиться обмежити — додамо `company_id` на config (не на stage). |
| 10 | Клонування вакансії | Copy `stage_config_ids` копіює і override-и (email template, visible, sequence). Specific-стадії дублюємо у job_ids нового job (через `copy=True` на config). |
| 11 | Concurrency: двоє редагують одну стадію | Стандартний Odoo optimistic lock. |
| 12 | Існуючий код `hr_recruitment_test_task._manage_test_task_stages` пише `stage.template_id` глобально | **Рефакторимо** — пише в `hr.job.stage.config.mail_template_id` для цього job. Видаляємо `CRITICAL FIX` хак. |
| 13 | Міграція існуючих даних | Скрипт у `migrations/<ver>/post-migrate.py`: для кожної існуючої `hr.recruitment.stage` з `job_ids` створюємо config-рядки з `visible=True`, `mail_template_id=stage.template_id`. Глобальні стадії не чіпаємо. |
| 14 | Перформанс kanban для job із багатьма стадіями | `_read_group_stage_ids` — один SQL join на `hr.job.stage.config`, індекси на FK. Profiled на ~100 стадіях. |
| 15 | API/Genio ATS інтеграція (майбутня) | Експозиція через `hr.applicant.stage_id` лишається стабільною. Конфігурація per-job — внутрішня. |
| 16 | Кандидат переходить між вакансіями (job_id change) | Stage_id може стати «недоступним» для нової вакансії. Onchange: skidnut на дефолтну стадію нової вакансії. |
| 17 | Перейменування IQ Test → Cognitive Test (інша задача) | Не блокує цю архітектуру. Стадія "IQ Test" → "Cognitive Test" — це client-facing label, керується або через переклад, або через `display_name`. |
| 18 | Видалення `hr.job.stage.config.link` після того як email уже відправлено | Не впливає на existing email-логи: тіло листа immutable у chatter (`mail.message.body`). Cascade видаляє запис лише з конфігурації майбутніх рендерів. |
| 19 | Невалідний URL у `hr.job.stage.config.link.url` (`ftp://`, `javascript:`, локальні шляхи) | Python `@api.constrains('url')` із regex `^https?://`. ValidationError інлайном у tree-list. Жодних silent-fail на email render. |
| 20 | `use_per_job_test_task_links=False` на job, але link_ids уже заповнені у config-рядках | UI секція ховається `attrs invisible`, email Jinja-loop skipped. Дані лишаються в БД — toggle назад на `True` миттєво відновлює. Жодних мутацій link_ids при toggle. |
| 21 | Колізія: `hr_recruitment_test_task.get_test_task_url()` (submission portal) і нові `link_ids` (resources) | Ортогональні. Submission portal лишається в тілі листа як був (через `object.get_test_task_url()`), `<ul>` з link_ids — додатковий блок. Жодного рефактору `get_test_task_url`. |

## 5. Послідовність впровадження (рекомендовані PRs)

**PR 1 — Foundation:** новий модуль `hr_recruitment_job_stage_config` з
моделлю `hr.job.stage.config`, scope-перемикач, override `default_get`
+ `_read_group_stage_ids`, мінімальний UI (вкладка Stages на job),
міграція. Старий код продовжує працювати.

**PR 2 — Email templates per job:** перенесення fallback chain у
`_track_template`. Рефакторинг `hr_recruitment_test_task` щоб писати
у config, а не в `stage.template_id`. Видалення `CRITICAL FIX` хаку.

**PR 3 — Hide stages per job:** UI кнопка/тогл на вкладці Stages,
wizard підтвердження.

**PR 4 — Call stage / booking link:** окремий sub-module
`hr_recruitment_call_stage` з полем `booking_link_id` і інтеграцією
у mail template (плейсхолдер `{{ stage_config.booking_link_id.url }}`).

**PR 5 — Test task description per job:** UI на вкладці Stages +
використання `config.test_task_description` у
`hr_recruitment_test_task` замість стадійного.

Кожен PR — окрема міграція версій модуля, окремий guide-файл усередині
модуля per `CLAUDE.md`.

## 6. Testing strategy

- **Unit:** `tests/test_stage_scope.py` — створення стадії з контексту
  job, ідемпотентність `_compute_scope`, fallback chain template.
- **Unit:** `tests/test_job_stage_config.py` — CRUD, unique constraint,
  cascade видалення, copy при дублюванні job.
- **Integration:** `tests/test_kanban_filtering.py` — рекрутер у job A
  не бачить стадії job B; глобальна стадія видима всюди, окрім тих job,
  де `visible=False`.
- **Migration:** `tests/test_migration.py` — на снапшоті з існуючими
  даними старі стадії з `job_ids` отримують коректні config-рядки.
- **UX manual:** скрипт у `scripts/qa_recruitment_stages.md` —
  чеклист із 10 сценаріїв (створення global, створення specific,
  перемикання scope, hide, override template, …).

## 7. Питання, які залишаються відкритими (попросити уточнення перед PR 1)

1. **Доступи (`groups`) на `scope='global'`** — обмежувати лише HR
   Manager, чи поки лишати всім? (Користувач відповів «поки не знаю» —
   ставимо TODO у код, не блокуємо PR 1.)
2. **Per-job rename стадії** (point 6 у edge-cases) — чи треба?
   Якщо так, додаємо `display_name` на `hr.job.stage.config`.
3. **Booking link** — використовувати `calendar.appointment.type` (з
   модуля `appointment`) чи інший providers (Calendly URL string)?
   Впливає на залежності модуля.
4. **Genio ATS** — чи буде Genio синхронізувати стадії через API?
   Якщо так, треба передбачити external_id mapping на рівні стадії
   (можна на `hr.job.stage.config` теж, якщо mapping per-job).
5. **«Cognitive Test» rename** — це окремий PR, чи поєднуємо з PR 1
   щоб не мати конфліктів у назві стадії "IQ Test"?

> Перед стартом PR 1 хочеться отримати відповіді хоча б на (1) і (3).

