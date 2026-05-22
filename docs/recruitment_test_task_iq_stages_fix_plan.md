# Recruitment — Test Task / Cognitive Assessment Stages — Bug Analysis & Fix Plan

> **Дата:** 2026-05-21
> **Статус:** PLAN — кодинг не починаємо, поки користувач не затвердив підхід.
> **Аудиторія:** AI-агент-виконавець + рев'юер.
> **Стосується модулів:** `hr_recruitment_test_task`, `iq_tests_survey`,
> `hr_recruitment_job_stage_config`.
> **Companion docs:**
> [`recruitment_master_plan.md`](./recruitment_master_plan.md) (§3 PR 1b/2),
> [`recruitment_vacancy_stages_flow.md`](./recruitment_vacancy_stages_flow.md).

---

## 1. Очікувана (правильна) поведінка

### 1.1. Test Task стейджі

1. У формі вакансії (`hr.job`) є чек-бокс **«Add Test Task»** (`add_test_task`).
2. Коли recruiter ставить галочку:
   - 3 стейджі — **Test Task Given**, **Test Task Submitted**,
     **Test Task ChatGPT Analyzed** — стають **видимі в kanban
     кандидатів цієї конкретної вакансії** (і тільки її).
   - У kanban інших вакансій вони НЕ з'являються.
3. Коли recruiter знімає галочку:
   - Стейджі НЕ видаляються (там можуть бути кандидати, R10 safety).
   - У kanban цієї вакансії вони стають приховані за дефолтом.
   - Існуючі кандидати на цих стейджах лишаються доступні через вкладку
     Stages у формі вакансії та фільтр «Include hidden stages».

### 1.2. Cognitive Assessment стейджі (бекенд — IQ)

1. У формі вакансії є чек-бокс **«Add Cognitive Assessment»** (`add_iq_test`).
   **Backend-нейминг лишається `iq_*`** (поля, моделі, методи); **юзер-фейсінг
   усюди — «Cognitive Assessment»**.
2. Коли recruiter ставить галочку:
   - Створюється `iq.survey` (з усіма 60 питаннями Raven's Progressive
     Matrices). Заголовок survey: `{job.name} - Cognitive Assessment`.
   - 2 стейджі — **Cognitive Assessment Assigned**,
     **Cognitive Assessment Completed** — стають **видимі в kanban
     кандидатів цієї конкретної вакансії**.
   - Стейдж «Assigned» має mail template `mail_template_iq_invite`
     (per-job override, НЕ глобальний `stage.template_id`).
3. Коли recruiter знімає галочку:
   - Survey НЕ видаляється (там можуть бути результати).
   - Стейджі НЕ видаляються (R10 safety).
   - У kanban цієї вакансії стейджі стають приховані за дефолтом.

### 1.3. Нейминг — однозначне правило (HARD RULE — нічого не ламати на бекенді)

**Backend лишається `iq_*` точно так, як він був.** Жодних перейменувань
моделей, полів, методів, XML ID, security груп, ir.model.access, URL
routes, mail template id-шників. На ці імена вже посилаються інші
модулі, mail templates, security records, та збережені у БД дані —
будь-який рейнейм їх ламає.

| Шар | Назва | Приклади |
|---|---|---|
| **Backend** (Python, моделі, поля, методи, XML ID, technical names, URL routes, security ACL) — **не чіпаємо** | `iq_*` | `iq.survey`, `iq.question`, `iq.user_input`, `iq.user_input.line`, `add_iq_test`, `iq_survey_id`, `iq_access_token`, `iq_score`, `iq_category`, `iq_input_id`, `_create_iq_test_infrastructure`, `_get_iq_test_url`, `mail_template_iq_invite`, `group_iq_user`, `group_iq_manager`, `module_category_iq_tests`, `model_iq_*`, `access_iq_*`, `/iq-test/*` |
| **Frontend / UI** (field strings, view labels, menus, email subject, survey title, stage names) | `Cognitive Assessment(s)` | поле string="Add Cognitive Assessment", stage="Cognitive Assessment Assigned/Completed", root menu "Cognitive Assessments" (XML ID лишається `menu_iq_root`), menu "My Cognitive Assessments" (XML ID лишається `menu_my_iq_tests`), survey title "{Job} - Cognitive Assessment" |

Будь-який новий backend-код **повинен** використовувати наявні `iq_*`
імена; будь-який новий UI-текст **повинен** говорити «Cognitive
Assessment(s)». Якщо ці два світи розходяться у поточному коді — **фікс
це UI-стрінга, а не backend-символ**.

---

## 2. Root Cause Analysis

### 2.1. Bug 1 — стейджі Test Task / Cognitive приховані у kanban

**Симптом:** галочка `add_test_task=True` (або `add_iq_test=True`) поставлена,
але відповідні колонки не з'являються у kanban кандидатів цієї вакансії.

**Слідова стежка:**

1. `hr_recruitment_test_task/models/hr_job.py::_manage_test_task_stages(True)`
   виконує:
   ```python
   stages.write({'job_ids': [(4, self.id)]})
   ```
   Аналогічно `iq_tests_survey/models/hr_job.py::_create_iq_test_infrastructure`
   робить `stage.write({'job_ids': [(4, self.id)]})` для двох
   Cognitive-стейджів.
2. На `hr.recruitment.stage` (з модуля `hr_recruitment_job_stage_config`)
   полі `scope` — `compute='_compute_scope'`, `store=True`,
   `@api.depends('job_ids')`. Після кроку 1 `scope` стає `'specific'`.
3. `hr.applicant._read_group_stage_ids` (override з того ж модуля):
   - Для `scope='specific'` стейдж видимий тільки якщо існує
     `hr.job.stage.config` рядок з `(job_id, stage_id, visible=True)`.
   - **Рядок НЕ створено** — ні `_manage_test_task_stages`, ні
     `_create_iq_test_infrastructure` не торкаються `hr.job.stage.config`.
4. Інверс `_inverse_scope` на `hr.recruitment.stage` СТВОРЮЄ config-рядок,
   але викликається тільки коли `scope` пишеться **явно** (через UI
   switcher), не коли він **обчислюється** від змін у `job_ids`.

**Дослідча примітка:** коментар у поточному коді
`hr_recruitment_job_stage_config/models/hr_recruitment_stage.py::write` каже
«let the inverse handle config-row reconciliation» — це **невірно** для
випадку, коли `job_ids` пишуть напряму. Інверс ловить лише запис у
`scope`, а не зміни у `job_ids`. Це і є фактичний root cause.

### 2.2. Bug 2 — IQ Test «перестав працювати»

Той самий root cause: галочка `add_iq_test=True` додає вакансію до
Cognitive-стейджів через `job_ids`, але без config-рядка → стейджі
приховані у kanban → recruiter не бачить колонок «Cognitive Assessment
Assigned/Completed» → впевнений що тест «не запускається».

Survey та email фактично створюються коректно — проблема **тільки** у
видимості стейджів. Це підтверджується тим, що
`_create_iq_test_infrastructure` повертається без exception і
`iq_survey_id` заповнюється.

Frontend-нейминг ("Cognitive Assessment") вже на місці; backend ще `iq_*`
— відповідає правилу §1.3. Користувач помилково сприймає різницю в
найменуваннях як «підставилось щось інше», бо взагалі не бачить
стейджів у kanban (Bug 1) і шукає причину.

### 2.3. Bug 3 (secondary) — `_create_iq_test_infrastructure` пише `stage.template_id` глобально

```python
# iq_tests_survey/models/hr_job.py
if stage_assigned.template_id != self.env.ref('iq_tests_survey.mail_template_iq_invite', ...):
    stage_assigned.write({'template_id': self.env.ref(...).id})
```

Це той самий анти-патерн, який видалили у PR 2 для `hr_recruitment_test_task`
(див. `recruitment_master_plan.md` §3 Фаза 1). Якщо 2 вакансії мають
`add_iq_test=True` з різними кастомними шаблонами — останній запис
перетирає попередній **глобально** для всіх вакансій, що використовують
цей стейдж. Source of truth має бути `hr.job.stage.config.mail_template_id`.

### 2.4. Bug 4 (latent) — write `stage.template_id` у test_task

PR 2 у master plan вже декларує, що `_manage_test_task_stages` НЕ повинен
писати `stage.template_id`. Перевірити чи ця рекомендація реально
імплементована у поточному `hr_recruitment_test_task` v17.0.1.0.4
(візуально код не пише — `_manage_test_task_stages` лише чіпає
`job_ids`). OK. Тоді актуальна частина PR 2 закрита; залишається таку
саму гігієну зробити для IQ.

---

## 3. Опції виправлення

### Опція A. Централізований фікс у `hr_recruitment_job_stage_config`

**Що робимо:** додаємо override `hr.recruitment.stage.write` (і
`create`), який детектує зміни `job_ids` (add/remove) і атомарно
синхронізує `hr.job.stage.config` рядки:

- При додаванні job-у до `job_ids` → створити (idempotent)
  `hr.job.stage.config` рядок з `visible=True`, `sequence=stage.sequence`
  (якщо рядка ще не існує). Якщо рядок існує — нічого не робимо
  (поважаємо ручне `visible=False`).
- При видаленні job-у з `job_ids` → НЕ видаляємо config-рядок (R10:
  applicant може там бути). Видимість лишаємо як є.

**Плюси:**
- Один точковий фікс — будь-який майбутній модуль, який пише в
  `stage.job_ids`, отримує правильну поведінку безкоштовно.
- Узгоджується з існуючою `_inverse_scope` логікою (idempotent create).
- Архітектурно правильно: per-job-stage стан live в одній моделі.

**Мінуси:**
- Магія: модулі не знають, що config-рядки створюються автоматично.
  Менш explicit для нових розробників.

### Опція B. Локальні фікси у `hr_recruitment_test_task` та `iq_tests_survey`

**Що робимо:**
- `_manage_test_task_stages(True)` додатково створює `hr.job.stage.config`
  рядки з `visible=True` для трьох test-task стейджів.
- `_create_iq_test_infrastructure` робить те саме для двох
  Cognitive-стейджів.
- Бонус (Bug 3 fix): `_create_iq_test_infrastructure` пише
  `mail_template_id=mail_template_iq_invite` у config-рядок «Assigned»,
  а **не** у `stage.template_id`.

**Плюси:**
- Explicit — модуль сам відповідає за свою інфраструктуру.
- Закриває Bug 3 (template_id глобальний) тим самим патчем.

**Мінуси:**
- Дублювання логіки create-config. Якщо завтра з'явиться третій модуль
  (наприклад, «Add Call Stage»), він теж буде змушений писати ту саму
  утиліту.
- Не захищає від майбутніх регресій у downstream-модулях.

### Опція C (Recommended). Гібрид — A + B + backfill

**Що робимо:**

1. **Опція A** — додаємо в `hr_recruitment_job_stage_config` defensive
   auto-create config-рядків при зміні `stage.job_ids`. Це foundation-fix.
2. **Опція B (підмножина — тільки Bug 3 fix):** у `iq_tests_survey`
   міняємо запис `stage.template_id` на запис
   `hr.job.stage.config.mail_template_id` (per-job). У
   `hr_recruitment_test_task` уже OK після PR 2.
3. **Backfill миграція** у `hr_recruitment_job_stage_config`
   (`migrations/17.0.1.0.2/post-migrate.py`): для кожної існуючої
   `hr.recruitment.stage` з непорожнім `job_ids` створити відсутні
   config-рядки з `visible=True`. Покриває юзерів, у яких чек-бокс уже
   стояв до релізу фіксу — інакше вони лишаться зі схованими стейджами
   після upgrade.
4. **Documentation pass:** оновити `GUIDANCE.md` у обох модулях
   (`hr_recruitment_test_task`, `iq_tests_survey`) і
   `hr_recruitment_job_stage_config/GUIDANCE.md` з поясненням нової
   інваріанти.

**Плюси:**
- Поточний баг закривається в усіх кутах (UI flow, upgrade flow, нові
  модулі у майбутньому).
- Bug 3 виправляється «по дорозі» з мінімальним діффом у IQ модулі.
- R2 / additive guarantee збережено — нічого не видаляємо, тільки
  створюємо відсутні рядки.

**Мінуси:**
- Більший PR (3 модулі, 1 міграція). Але кожен фрагмент маленький
  і незалежно тестується.

### Оцінка по критеріях з CLAUDE.md

| Критерій | A | B | **C** |
|---|---|---|---|
| Quality of solution | 8/10 | 6/10 | **9/10** |
| User Experience (recruiter) | 8/10 | 8/10 | **10/10** (включно з upgrade-юзерами) |
| Supportability | 9/10 (single fix) | 6/10 (дубль) | **9/10** |
| Ризик регресії | низький | середній | низький (additive) |
| Розмір змін | XS | S | M |

**Рекомендація:** Опція C.

---

## 4. План впровадження (Опція C)

### 4.1. PR — `hr_recruitment_job_stage_config` v17.0.1.0.2

**Файли:**

- `models/hr_recruitment_stage.py`:
  - Override `write` — детектує зміни в `job_ids` (commands
    `(4, id)`, `(6, 0, ids)`, `(3, id)`, `(5, 0, 0)`), після `super()`
    обчислює дельту added/removed job-IDs і викликає helper
    `_sync_configs_for_added_jobs(added_jobs)`.
  - Override `create` — після super, для кожного нового стейджа з
    непорожнім `job_ids` створює config-рядки з `visible=True`.
  - Helper `_sync_configs_for_added_jobs(jobs)`:
    - Для кожного `(stage, job)` пари: idempotent create config row з
      `visible=True`, `sequence=stage.sequence`. Якщо рядок існує —
      нічого не робимо.
    - НЕ створюємо рядки для пар, де config вже існує (поважаємо ручне
      `visible=False`).
- `migrations/17.0.1.0.2/post-migrate.py`:
  - Для кожної `(stage, job)` пари з `stage.job_ids` без config-рядка
    — створити рядок з `visible=True`.
  - Idempotent: re-run не створює дублікатів.
  - Логування у `ir.logging` під тегом
    `hr_recruitment_job_stage_config.migration` (як у попередніх
    міграціях цього модуля).
- `__manifest__.py`: bump version → `17.0.1.0.2`.
- `tests/test_stage_write_creates_config.py`:
  - test: `stage.write({'job_ids': [(4, job.id)]})` створює config-рядок.
  - test: повторний write — створює рівно 0 нових рядків.
  - test: write з `(3, job.id)` НЕ видаляє існуючий config-рядок.
  - test: створення нового стейджа з `job_ids=[job.id]` створює
    config-рядок з `visible=True`.
- `GUIDANCE.md`: додати секцію «How config rows are auto-created from
  job_ids writes» з посиланням на новий тест.

### 4.2. PR — `iq_tests_survey` v17.0.1.4.0

**Файли:**

- `models/hr_job.py::_create_iq_test_infrastructure`:
  - Прибрати запис `stage_assigned.write({'template_id': ...})`.
  - Натомість після `stage_assigned.write({'job_ids': [(4, self.id)]})`
    знайти/створити `hr.job.stage.config` рядок для `(self, stage_assigned)`
    і записати `mail_template_id=mail_template_iq_invite`.
  - Те саме для стейджа «Assigned» при шляху `Stage.create`.
  - При створенні нового стейджа можна одразу передати `job_ids`
    в `create` — фікс із 4.1 створить config-рядок (через override
    `create`) і це покриє новий path.
- `GUIDE.md`: оновити секцію «Recruitment Flow» з правильною
  термінологією (backend `iq_*`, frontend "Cognitive Assessment") і
  явно зафіксувати, що template живе в `hr.job.stage.config`, не на
  `stage.template_id`.
- `__manifest__.py`: bump version → `17.0.1.4.0`.
- `tests/test_create_iq_test_infrastructure.py` (новий):
  - Включення `add_iq_test=True` створює survey, додає job до 2
    стейджів, **і створює 2 config-рядки з `visible=True`**.
  - Включення `add_iq_test=True` на 2 різних вакансіях не перетирає
    `stage.template_id` (assertion).
  - Per-job template живе у `config.mail_template_id`.

### 4.3. PR — `hr_recruitment_test_task` v17.0.1.0.5 (мінімальний)

**Файли:**

- Жодних змін у логіці `_manage_test_task_stages` (вже коректний —
  після 4.1 config-рядки створяться автоматично через стейдж-write
  override).
- `GUIDANCE.md` (новий — поточний модуль його не має):
  - «What this module does».
  - Як працює `_manage_test_task_stages` тепер: пише в `job_ids`,
    foundation-модуль автоматично створює config-рядки.
  - **Чому НЕ слід додавати власну create-config логіку** (single
    source of truth у foundation-модулі).
- `__manifest__.py`: bump version → `17.0.1.0.5`.
- `tests/test_add_test_task_makes_stages_visible.py` (новий):
  - Включення `add_test_task=True` → 3 стейджі видимі у kanban цієї
    вакансії (через `_read_group_stage_ids`).
  - Включення на 2 вакансіях → 3 стейджі видимі **у обох**.
  - Інша вакансія без галочки → жоден з 3 стейджів НЕ видимий у її
    kanban.

### 4.4. Sequence та компатибельність

Порядок мерджу:
1. **4.1** (foundation) — мерджимо першим, isolated.
2. **4.2** і **4.3** — паралельно, обидва залежать від 4.1.
3. Релізне вікно одне (atomic як у PR 1b+2).

**Назад-сумісність:**
- Існуючі бази після post-migrate отримують відсутні config-рядки →
  стейджі стають видимі без жодної дії від recruiter.
- Якщо recruiter раніше **вручну** виставив `config.visible=False` —
  він НЕ перетирається (idempotent skip).
- Жоден `applicant.stage_id` не змінюється (R2 guarantee — verified у
  post-migrate diff snapshot, як у попередніх міграціях).

### 4.5. Manual QA scenarios (під ручний тест перед relesase)

1. Створити нову вакансію, поставити `add_test_task=True` → відкрити
   kanban → бачимо 3 нових колонки.
2. Зняти `add_test_task` → колонки зникають з kanban, але якщо там
   був кандидат — стейдж лишається видимим (safety).
3. Створити нову вакансію, поставити `add_iq_test=True` → відкрити
   kanban → бачимо 2 Cognitive-колонки. Survey створено, email
   template виставлено per-job.
4. На існуючій базі з вакансією, де `add_test_task=True` ще ДО
   фіксу: upgrade модуля → post-migrate backfill → відкрити kanban →
   3 колонки тепер видимі.
5. На вакансії з обома галочками → 5 додаткових колонок у kanban.
6. Перевірити Configuration → Recruitment → Stages → стейджі
   позначені scope=specific з правильними job_ids.

---

## 5. Що **НЕ** робимо у цьому фіксі (out of scope)

- Не чіпаємо `hr.applicant._read_group_stage_ids` логіку — вона
  правильна, проблема була у тому, що config-рядки не створювались.
- Не міняємо frontend-нейминг «Cognitive Assessment» назад на «IQ Test»
  — він і має бути «Cognitive» у UI (правило §1.3).
- **Не перейменовуємо ЖОДЕН backend-символ.** `iq_*` лишається `iq_*`
  — моделі, поля, методи, XML ID, security groups, ir.model.access,
  URL routes, mail templates. Правило §1.3 — hard. У цьому фіксі НЕ
  чіпаємо `iq.survey`, `iq.question`, `iq.user_input`, `add_iq_test`,
  `iq_survey_id`, `_create_iq_test_infrastructure`, `mail_template_iq_invite`,
  тощо. Будь-який backend-рейнейм — окремий PR з явним обговоренням
  (і він майже завжди не потрібен).
- Не додаємо новий UI або фільтри — це питання master plan PR 3.
- Не чіпаємо `hr_recruitment_test_task` логіку email render (PR 2 +
  PR 4 у master plan).

---

## 6. Acceptance criteria (вся затія в одному списку)

- [ ] Включення `add_test_task=True` робить 3 test-task стейджі
  видимими у kanban цієї вакансії — **без додаткових кліків**.
- [ ] Включення `add_iq_test=True` робить 2 Cognitive стейджі
  видимими у kanban цієї вакансії — **без додаткових кліків**.
- [ ] Survey IQ створюється з правильним заголовком, 60 питань,
  email template `mail_template_iq_invite` живе per-job у
  `hr.job.stage.config.mail_template_id`.
- [ ] Жоден `applicant.stage_id` не змінено міграцією (R2 verified).
- [ ] Жодна вакансія без галочок не отримала нових видимих стейджів.
- [ ] Backend моделі/поля лишились `iq_*`; UI/frontend усюди
  «Cognitive Assessment».
- [ ] Усі нові тести зелені; усі попередні тести зелені.
- [ ] `GUIDANCE.md` оновлений у трьох модулях.
- [ ] `recruitment_master_plan.md` отримав посилання на цей документ.

---

## 7. Питання до користувача (перед стартом імплементації)

1. **Затвердження Опції C** — ОК продовжувати з гібридним підходом
   (foundation override + локальний Bug 3 fix + backfill migration)?
2. **Backfill scope:** запускати backfill для **усіх** існуючих
   `(stage, job)` пар де `stage.job_ids ∋ job` без config-рядка
   (рекомендовано), або тільки для test-task / IQ стейджів за іменем?
3. **Test coverage:** OK додати інтеграційний тест на
   `_read_group_stage_ids` фактично повертає 3 стейджі при
   `add_test_task=True`, чи достатньо тесту що config-рядки створено?

---

## 8. Новий скоуп — per-vacancy test-task link

**Запит користувача:** при `add_test_task=True` у формі вакансії
відкривається поле «Test Task Link» (наприклад, посилання на git
репозиторій з ТЗ). Це посилання має рендеритись у тілі email-листа
`mail_template_test_task_invite` як кнопка **після слова
«Description:»**, унікальна для кожної вакансії. Сам email-template
лишається глобальним; per-vacancy частина — тільки сам URL.

### 8.1. Консиліум — 4 перспективи

| Кут | Думка | Висновок |
|---|---|---|
| **Data Model architect** | Foundation модуль уже резервує `hr.job.stage.config.link_ids` (One2many) під PR 4 — список іменованих URL per (job × stage). Це over-engineered для одного посилання per-job: рекрутер мусить додати рядок у дочірній моделі, заповнити label+url, тоді як йому треба ввести один URL. | Зберігаємо одне посилання як **`Char` на `hr.job`** (`test_task_link`). Якщо завтра знадобиться кілька — мігруємо в `link_ids` (foundation уже готовий). |
| **UX / Recruiter** | Поле має з'являтись поруч із чекбоксом `add_test_task`, бажано на тій самій лінії або відразу під ним. Hide коли чекбокс False (через `invisible="not add_test_task"`). Widget `url` для inline-превʼю/кліку. URL placeholder приклад "https://github.com/org/test-task-frontend". | Поле з'являється inline, кnocking-зміни — тільки якщо чекбокс True. При знятті чекбоксу значення **не очищаємо** (recruiter може поставити галочку назад). |
| **Email rendering** | Email template — глобальний (`mail_template_test_task_invite`). Per-job частина рендериться через `{{ object.job_id.test_task_link }}` у тілі листа. **Jinja `{% if %}` гард** обовʼязковий — інакше при порожньому полі ми рендеримо `<a href="">` зламану кнопку. Помістити секцію `Description:` + кнопку **до** існуючої `View Task & Submit` (зберігаємо submission flow), щоб candidate спершу бачив завдання, а потім submit-портал. | Один глобальний template; Jinja conditional; додати `<strong>Description:</strong>` рядок і кнопку «Open Test Task» що рендериться тільки якщо `test_task_link` непорожнє. |
| **Migration / Safety** | Існуючі вакансії з `add_test_task=True` не мають `test_task_link` → button не рендериться (правильно). Якщо recruiter додає `test_task_link` ПІСЛЯ того як кандидат отримав email — старий email вже відправлений (immutable у chatter), наступні кандидати отримають нову кнопку. Це normal/очікувана поведінка. Multi-language: button label «Open Test Task» через `t-out` із translation. Copy job: `test_task_link` копіюється з рештою полів (`copy=True` default). | Жодної міграції не потрібно — нове поле default `False`. Tracking на полі (`tracking=True`) щоб recruiter бачив зміни URL у chatter вакансії. |

### 8.2. Дизайн (фінальний)

**Backend (`hr_recruitment_test_task` v17.0.1.0.5):**

```python
# models/hr_job.py
test_task_link = fields.Char(
    string='Test Task Link',
    tracking=True,
    help='URL to the test task (e.g., GitHub repository with the spec). '
         'Rendered as a clickable button in the test-task invitation '
         'email. Unique per vacancy.')

@api.constrains('test_task_link')
def _check_test_task_link(self):
    pattern = re.compile(r'^https?://', re.IGNORECASE)
    for job in self:
        if job.test_task_link and not pattern.match(job.test_task_link):
            raise ValidationError(_(
                "Test Task Link '%s' must start with http:// or https://.",
                job.test_task_link))
```

**View (`hr_recruitment_test_task/views/hr_job_views.xml`):**

```xml
<xpath expr="//group[@name='recruitment']" position="inside">
    <field name="add_test_task"/>
    <field name="test_task_link" widget="url"
           invisible="not add_test_task"
           placeholder="https://github.com/org/test-task"/>
</xpath>
```

**Email (`hr_recruitment_test_task/data/mail_data.xml`):**

```xml
<!-- після рядка з «...for the {{ object.job_id.name }} position.»: -->
<t t-if="object.job_id.test_task_link">
    <p style="margin: 12px 0px 4px 0px; font-size: 13px;">
        <strong>Description:</strong>
    </p>
    <div style="text-align: center; margin: 8px 0px 16px 0px;">
        <a t-att-href="object.job_id.test_task_link"
           style="background-color: #017E84; padding: 8px 16px; text-decoration: none; color: #fff; border-radius: 5px; font-size: 14px;">
           Open Test Task
        </a>
    </div>
</t>
```

(інший контент листа лишається; «View Task &amp; Submit» залишається
як був — інший CTA, ortogonal до нової кнопки)

### 8.3. Edge cases (8.x specific)

| # | Edge-case | Поведінка |
|---|---|---|
| 8.1 | `test_task_link=''` або None | Jinja `t-if` → нова секція не рендериться. Існуючий submit-button лишається. |
| 8.2 | Невалідний URL (`ftp://...`, `javascript:...`, `/relative/path`) | `@api.constrains` regex `^https?://` → ValidationError при save. Помилка inline у формі. |
| 8.3 | Recruiter знімає `add_test_task` | Поле ховається з UI; значення **не очищається** (db column лишається). Якщо поставлять знову — поле з тим самим URL. |
| 8.4 | Recruiter міняє `test_task_link` після того як кандидат отримав email | Старий email immutable у chatter. Нові кандидати отримають нову кнопку. (`tracking=True` → recruiter бачить зміну у chatter вакансії.) |
| 8.5 | Job duplicate (Action → Duplicate) | `test_task_link` копіюється разом з рештою полів (`copy=True` default на Char). |
| 8.6 | Multi-company: URL вакансії компанії A може бути приватний git-репо | Жодної company-валідації — recruiter сам відповідає, кому шле listing. |
| 8.7 | Email-template недоступний (видалили з UI) | Той самий fallback як зараз: `_track_template` returns без template → нічого не шлемо. Нова кнопка не впливає. |
| 8.8 | XSS у URL (recruiter ввів `https://evil.com/?<script>...`) | Mail template `t-att-href` робить proper escape атрибута; ризику XSS немає. Browser сам обробляє query string. |
| 8.9 | Локалізація: «Description:» / «Open Test Task» | Лишаємо англійську у template (`mail.template` тіло англійською, як і решта існуючого). Якщо потрібен i18n — окремий PR per-language template. |
| 8.10 | Кандидат у стейджі «Test Task Given» уже **до** додавання поля | Якщо recruiter заповнить `test_task_link` зараз — нові email-и матимуть кнопку; старі — без неї. Це нормально. |

### 8.4. Acceptance criteria (фіча test_task_link)

- [ ] У формі вакансії при `add_test_task=True` зʼявляється поле
  «Test Task Link». При `False` — ховається.
- [ ] Невалідний URL → ValidationError inline у формі.
- [ ] При відправці email кандидату на стейдж «Test Task Given» з
  непорожнім `test_task_link` — у тілі листа є секція
  «Description:» + кнопка «Open Test Task» що веде на URL вакансії.
- [ ] При порожньому `test_task_link` — секція не рендериться;
  existing submit-кнопка лишається.
- [ ] Дві вакансії з різними URL → два кандидати отримують листи з
  різними кнопками.
- [ ] Зміна URL відображається у chatter вакансії (`tracking=True`).
- [ ] Job duplicate переносить `test_task_link`.

---

## 9. Фінальний короткий action plan (під апрув)

> **Скоуп:** §3 Опція C (stage visibility fix + IQ template fix) + §8
> (test_task_link). Три модулі, три PR, один release window.

### PR 1 — `hr_recruitment_job_stage_config` v17.0.1.0.2 (foundation)
- Override `hr.recruitment.stage.write` + `create` → auto-create
  `hr.job.stage.config` рядки з `visible=True` при додаванні в `job_ids`.
- `migrations/17.0.1.0.2/post-migrate.py` — backfill існуючих
  `(stage, job)` пар без config-рядків (idempotent).
- 4 unit-тести: write створює рядок, create створює, повторний write
  не дублює, remove з job_ids не видаляє рядок.
- Bump manifest.
- Update GUIDANCE.md (вже зроблено).

### PR 2 — `iq_tests_survey` v17.0.1.4.0 (IQ template fix)
- `_create_iq_test_infrastructure`: прибрати запис у
  `stage.template_id`. Натомість писати у
  `hr.job.stage.config.mail_template_id` для (job × «Assigned» stage).
- 2 unit-тести: 2 джоби з add_iq_test → 2 окремі config-рядки з
  template-ами; stage.template_id не пишеться.
- Bump manifest. Update GUIDE.md (вже зроблено).
- **Backend нейминг `iq_*` не чіпаємо** (§1.3 hard rule).

### PR 3 — `hr_recruitment_test_task` v17.0.1.0.5 (link feature)
- Додати поле `test_task_link` (Char, tracking, constrains regex
  https?://) на `hr.job`.
- View: поле inline після `add_test_task`, `invisible="not add_test_task"`,
  widget=url, placeholder з прикладом.
- Email: додати `Description:` + кнопка `Open Test Task` під
  conditional `t-if="object.job_id.test_task_link"`.
- 3 unit-тести: видимість поля, URL validation, button render у email.
- Bump manifest. Update GUIDANCE.md (вже створено у попередній ітерації).

### Order of execution
1. PR 1 спершу (foundation).
2. PR 2 + PR 3 паралельно (обидва залежать тільки від PR 1).
3. Один merge window — atomic release.

### Out of scope (повторно)
- Жодних backend-перейменувань (§1.3).
- Жодних змін у `_read_group_stage_ids` (вона коректна).
- Жодних UI-фільтрів / hide-stage wizard-ів (master plan PR 3).
- Жодного per-job override email-template для test_task у цій
  ітерації (master plan PR 4 — окрема історія).
