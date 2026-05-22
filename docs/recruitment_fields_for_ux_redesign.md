# Recruitment — Поля для UX/UI редизайну створення вакансії

Документ-чек-ліст для дизайнера. Тут зібрано:

- ✅ **Існуючі поля** — те, що вже є в моделях (стокових і кастомних
  `jito_modules`), і що рекрутер бачить/має бачити при створенні
  та редагуванні вакансії.
- 🆕 **Заплановані поля** — те, що ми збираємось додати згідно
  `recruitment_vacancy_stages_flow.md` (план PR 1–5) і суміжних
  задач (per-job stages config, call stage, test task per job,
  hide stage per job, IQ→Cognitive rename, Genio ATS).
- 💡 **UX-нотатки** — коментар, як це зараз згруповано і на що
  варто звернути увагу при перегрупуванні.

Скоуп — модель `hr.job` (вакансія) у першу чергу; у кінці —
короткий розділ про `hr.applicant` і `hr.recruitment.stage`,
бо UI вакансії частково керує цими сутностями.

---

## 1. `hr.job` — Картка вакансії (форма "New Job" і edit form)

### 1.1. Базова інформація (сток Odoo 17)

| Поле | Тип | Що це | Status |
|---|---|---|---|
| `name` | Char | Назва позиції ("Senior Python Developer") | ✅ |
| `department_id` | M2O `hr.department` | Відділ | ✅ |
| `company_id` | M2O `res.company` | Компанія (multi-company) | ✅ |
| `user_id` | M2O `res.users` | Recruiter (відповідальний) | ✅ |
| `hr_responsible_id` | M2O `res.users` | HR-відповідальний (підписант) | ✅ |
| `manager_id` | M2O `hr.employee` | Hiring manager | ✅ |
| `address_id` | M2O `res.partner` | Локація / адреса роботи | ✅ |
| `industry_id` | M2O `res.partner.industry` | Індустрія | ✅ |
| `contract_type_id` | M2O `hr.contract.type` | Тип контракту (full-time/part-time…) | ✅ |
| `employment_type_id` | M2O (enterprise) | Employment type | ✅ |
| `description` | Html | Базовий опис вакансії (rich-text) | ✅ |
| `requirements` | Text | Вимоги (legacy text-поле) | ✅ |
| `no_of_recruitment` | Integer | Цільова к-сть hires | ✅ |
| `no_of_hired_employee` | Integer (compute) | Скільки вже найнято | ✅ |
| `state` | Selection | `recruit` (Recruiting) / `open` (Not recruiting) | ✅ |
| `date_from`, `date_to` | Date | Період активності вакансії | ✅ |
| `expected_employees` | Integer | Очікувана к-сть співробітників на позиції | ✅ |
| `kanban_state` | Selection | Normal / Done / Blocked | ✅ |
| `color` | Integer | Колір на kanban | ✅ |
| `favorite_user_ids` | M2M | Хто додав у обране | ✅ |
| `website_published` | Boolean | Опубліковано на сайті | ✅ (через website_hr_recruitment) |
| `interviewer_ids` | M2M `res.users` | Інтерв'юери | ✅ |

💡 Сток-форма організована як: ліва шапка (name, recruiter), notebook
з вкладками "Recruitment", "Job Description", "Employees".

### 1.2. Vacancy page / web-публікація (`hr_recruitment_vacancy_page`)

| Поле | Тип | Що це | Status |
|---|---|---|---|
| `job_title` | Char | Окремий "веб"-заголовок (може відрізнятись від `name`) | ✅ |
| `job_description_context` | Html | Розширений контекст вакансії (для AI + сайту) | ✅ |
| `experience_years_min` | Integer | Мін. років досвіду | ✅ |
| `experience_years_max` | Integer | Макс. років досвіду | ✅ |
| `process_time_to_answer` | Char | Скільки днів до відповіді (для кандидата) | ✅ |
| `process_steps` | Text | Опис кроків процесу найму | ✅ |
| `process_days_to_offer` | Char | Час до офера | ✅ |
| `use_published_config` | Boolean | Тогл: публікувати окрему "карточку" замість основних полів | ✅ |
| `published_title` | Char | Заголовок на публічній сторінці | ✅ |
| `published_short_desc` | Html | Короткий опис на сайті | ✅ |
| `published_long_desc` | Html | Повний опис на сайті | ✅ |
| `published_salary_display` | Char | Як показати ЗП ("$2000-3000", "Negotiable") | ✅ |
| `published_experience_display` | Char | Як показати досвід ("3+ years") | ✅ |

💡 Зараз ці поля живуть в окремій вкладці. Логіка двох режимів
(`use_published_config = on/off`) часто плутає рекрутерів — на дизайні
варто **явно** показати, що саме піде на сайт vs що тільки внутрішнє.

### 1.3. Теги (`hr_job_tags`)

| Поле | Тип | Що це | Status |
|---|---|---|---|
| `tag_ids` | M2M `hr.job.tag` | Теги для класифікації/фільтрації вакансій | ✅ |

### 1.4. AI / Job description extract (`hr_recruitment_extract_openai`)

| Поле | Тип | Що це | Status |
|---|---|---|---|
| `job_description_attachment_ids` | M2M `ir.attachment` | Вихідні PDF/DOCX опису вакансії | ✅ |
| `jd_extract_state` | Selection | `idle/processing/done/failed` — стан AI-екстракту JD | ✅ |
| `jd_extract_status` | Text | Текстовий статус (помилки, прогрес) | ✅ |
| `jd_processed_attachment_ids` | M2M | Оброблені AI-файли | ✅ |
| `jd_queue_job_uuid` | Char | ID черги (для tracking) | ✅ |
| `jd_job_state` | Selection | Стан фонової задачі | ✅ |
| `jd_processing_in_progress` | Boolean | UI-флаг для спіннера | ✅ |
| `requirement_statement_ids` | O2M `hr.job.requirement` | Витягнуті AI вимоги (структуровані) | ✅ |
| `has_requirements` | Boolean (compute) | Чи є хоч одна вимога | ✅ |
| `weight_experience` | Float | Вага "досвід" у фінальному AI-скорі | ✅ |
| `weight_project` | Float | Вага "проекти" | ✅ |
| `weight_company` | Float | Вага "компанії в резюме" | ✅ |
| `weight_credibility` | Float | Вага "довіра/надійність" | ✅ |
| `ai_match_mode` | Selection | Режим AI-метчингу (швидкий/повний) | ✅ |
| `cv_attachment_ids` | M2M | Завантажені CV для bulk-обробки | ✅ |
| `processed_cv_attachment_ids` | M2M | Оброблені CV | ✅ |
| `processed_cv_count` | Integer (compute) | Лічильник | ✅ |
| `failed_cv_count` | Integer (compute) | Лічильник помилок | ✅ |
| `total_cv_count` | Integer (compute) | Усього CV | ✅ |
| `run_ai_match_on_bulk` | Boolean | Запускати AI-match під час bulk | ✅ |
| `run_ai_experience_on_bulk` | Boolean | Запускати AI-experience під час bulk | ✅ |
| `bulk_queue_job_uuid` | Char | ID bulk-черги | ✅ |
| `bulk_job_state` | Selection | Стан bulk-обробки | ✅ |
| `bulk_processing_in_progress` | Boolean | UI-флаг | ✅ |
| `bulk_processing_complete` | Boolean | UI-флаг | ✅ |
| `bulk_processing_failed` | Boolean | UI-флаг | ✅ |
| `bulk_processing_progress` | Integer | % прогресу | ✅ |

💡 Усі AI-поля — це **окрема велика секція**. Для дизайну варто
зробити її як «AI Toolkit panel» з трьома станами: до запуску /
processing / done.

### 1.5. Application form (`hr_recruitment_forms`)

| Поле | Тип | Що це | Status |
|---|---|---|---|
| `use_forms` | Boolean | Увімкнути кастомну форму подачі замість дефолтної | ✅ |
| `form_show_phone` | Boolean | Показувати поле "телефон" у формі | ✅ |
| `form_show_linkedin` | Boolean | Показувати "LinkedIn URL" | ✅ |
| `form_show_resume` | Boolean | Показувати "Resume upload" | ✅ |
| `form_show_intro` | Boolean | Показувати "Short intro" | ✅ |
| `form_template_id` | M2O `hr.form.template` | Шаблон форми (preset) | ✅ |
| `question_line_ids` | O2M | Питання конкретно цієї вакансії | ✅ |
| `form_question_ids` | O2M | Доступні питання (з шаблону + override) | ✅ |
| `form_question_count` | Integer (compute) | Лічильник | ✅ |

💡 Це окрема велика секція "Application form". Зараз — табличний редактор
питань; рекрутерам важко зрозуміти, що "успадковано з шаблону" vs
"перевизначено вручну". Це місце для гарного дизайну (бейджі inherited/
overridden).

### 1.6. Test Task (`hr_recruitment_test_task`)

| Поле | Тип | Що це | Status |
|---|---|---|---|
| `add_test_task` | Boolean | Увімкнути стадію Test Task для цієї вакансії | ✅ |

💡 Зараз — один тогл. У плані (див. §3) — повний редактор опису
тестового завдання per-job per-stage.

### 1.7. Link trackers (`hr_recruitment_trackers`)

| Поле | Тип | Що це | Status |
|---|---|---|---|
| `tracker_ids` | O2M `hr.recruitment.tracker` | Трекери джерел кандидатів (UTM, посилання) | ✅ |
| `tracker_count` | Integer (compute) | Лічильник для smart-button | ✅ |

💡 Зараз — окрема вкладка/smart-button. На дизайні редизайну має
бути acessible з форми вакансії, але без перевантаження основного flow.

---

## 2. `hr.job` — 🆕 Заплановані поля (з roadmap)

Згідно `recruitment_vacancy_stages_flow.md` §1 і §2 (PR 1–5):

| Поле | Тип | Що це | PR |
|---|---|---|---|
| `stage_config_ids` | O2M `hr.job.stage.config` | Конфіг кожної стадії під цю вакансію (через through-model) | 🆕 PR 1 |
| `hidden_stage_count` | Integer (compute) | К-сть прихованих стадій (для плашки 🔒 у kanban) | 🆕 PR 3 |

💡 Найбільша візуальна зміна — нова вкладка **"Stages"** у формі вакансії
з editable tree:

```
| Drag | Seq | Stage              | Visible | Email Template     | Test Task Desc | Booking Link |
|------|-----|--------------------|---------|--------------------|----------------|--------------|
| ⠿    | 10  | Initial Qualif.    | ☑       | (default)          | —              | —            |
| ⠿    | 20  | Test Task          | ☑       | (override)         | (per-job HTML) | —            |
| ⠿    | 25  | Call               | ☑       | call_template      | —              | (booking)    |
| ⠿    | 30  | Contract           | ☐       | —                  | —              | —            |
| --- Hidden stages (1) ---                                                                       |
| ⠿    | 40  | Old Phone Screen   | 👁‍🗨 hidden | —              | —              | —            |
```

Плюс індикатор у kanban applicants: `🔒 3 stages hidden in this job · Manage`.

---

## 3. `hr.job.stage.config` — 🆕 Нова модель (PR 1)

Це через-модель `job × stage` з payload. Дизайнити її поля треба
**не як окрему форму**, а як **рядок editable tree** у вкладці Stages
форми вакансії.

| Поле | Тип | Що це |
|---|---|---|
| `job_id` | M2O `hr.job` | Вакансія (батько) |
| `stage_id` | M2O `hr.recruitment.stage` | Стадія |
| `sequence` | Integer | Порядок у межах цієї вакансії (drag-handle) |
| `visible` | Boolean | Чи показувати колонку у kanban цієї вакансії |
| `mail_template_id` | M2O `mail.template` | Per-job email override (з fallback на stage.template_id) |
| `test_task_description` | Html | Опис тестового завдання саме для цієї вакансії+стадії |
| `booking_link_id` | M2O `calendar.appointment.type` | Для "call stage" — лінк на бронювання |
| `display_name` | Char (опційно, PR-TBD) | Per-job rename стадії (відкрите питання) |

💡 На дизайні `mail_template_id`, `test_task_description`, `booking_link_id`
варто показати inline як **acordion-row** ("...expand to edit") або
як side-panel при кліку на рядок, щоб не перевантажувати tree.

---

## 4. `hr.recruitment.stage` — Стадія (глобальний каталог)

### 4.1. Існуючі поля (сток)

| Поле | Тип | Що це | Status |
|---|---|---|---|
| `name` | Char | Назва стадії | ✅ |
| `sequence` | Integer | Глобальний порядок | ✅ |
| `job_ids` | M2M `hr.job` | "Job Specific" — у яких вакансіях видима | ✅ |
| `template_id` | M2O `mail.template` | Email-шаблон при переході в стадію | ✅ |
| `requirements` | Text | Що повинно бути виконано на цій стадії | ✅ |
| `fold` | Boolean | Згорнута колонка в kanban | ✅ |
| `hired_stage` | Boolean | Це фінальна "Hired" стадія | ✅ |
| `legend_normal` | Char | Підпис kanban-state "Normal" | ✅ |
| `legend_blocked` | Char | Підпис "Blocked" | ✅ |
| `legend_done` | Char | Підпис "Done" | ✅ |

### 4.2. 🆕 Заплановані поля

| Поле | Тип | Що це | PR |
|---|---|---|---|
| `scope` | Selection (`global`/`specific`) | Перемикач Global vs Job-specific (з default-логікою з контексту) | 🆕 PR 1 |

💡 У формі стадії потрібен **scope-перемикач (radio)** + умовно
показуваний M2M `job_ids` (коли scope=specific). Плюс soft-банер на
старих глобальних стадіях: _"Stage is global. Convert to job-specific?"_

---

## 5. `hr.applicant` — Кандидат (контекст, бо UI вакансії на це впливає)

Поля кандидата редизайн вакансії напряму **не редагує**, але деякі з
них впливають на те, як виглядає kanban і рядки tree під вакансією
(тому корисно знати).

### 5.1. Базові сток-поля (релевантні)

`partner_name`, `email_from`, `phone`, `linkedin_profile`, `stage_id`,
`kanban_state`, `priority`, `user_id` (recruiter), `interviewer_ids`,
`job_id`, `department_id`, `source_id`, `medium_id`, `campaign_id`,
`type_id` (degree), `attachment_ids` (CV), `availability`, `salary_expected`,
`salary_proposed`, `categ_ids` (тeги).

### 5.2. Кастомні поля від модулів

| Поле | Звідки | Що це |
|---|---|---|
| `linkedin_profile` | extract_openai | LinkedIn URL (override стокового) |
| `openai_extract_state` / `_status` | extract_openai | Стан AI-парсингу CV |
| `ai_match_percent` | extract_openai | % метчингу до вакансії |
| `ai_match_summary_fit` / `_strengths` / `_gaps` | extract_openai | Резюме AI-аналізу |
| `ai_match_state` / `_status` | extract_openai | Стан AI-метчингу |
| `ai_match_mode` | extract_openai | Режим (швидкий/повний) |
| `experience_ids` (O2M) | extract_openai | Витягнуті записи досвіду |
| `ai_experience_score` | extract_openai | AI-оцінка досвіду |
| `job_hopping_coefficient` | extract_openai | Коеф. job-hopping |
| `experience_state` / `_status` | extract_openai | Стан AI-аналізу досвіду |
| `form_response_id` / `form_response_line_ids` | forms | Відповіді на форму |
| `has_form_response` | forms | Чи заповнено форму |
| `test_task_token` | test_task | Унікальний токен для submission-URL |
| `submission_ids` | test_task | Сабміти тестового завдання |
| `last_github_link` | test_task | Останній GitHub URL |
| `ai_analysis_score` | test_task | AI-оцінка тестового |
| `ai_analysis_summary` | test_task | AI-фідбек на тестове (HTML) |
| `tracker_id` | trackers | Який трекер привів цього кандидата |
| `tracking_value_ids` | trackers | Кастомні параметри (UTM-like) |
| `tracker_group_1..15` | trackers | Computed-групи для kanban-фільтрів |

---

## 6. Підсумкові групування для дизайну форми "New Job"

Пропоную при редизайні думати про **7 логічних блоків** замість
поточних "купи вкладок":

1. **Identity** — name, job_title, department, company, location, tags,
   contract_type, color, kanban_state, recruiter, hiring_manager.
2. **Headcount & timing** — no_of_recruitment, expected_employees,
   date_from/to, state.
3. **Description** — description (Html), requirements, AI JD upload
   (`job_description_attachment_ids`) + витягнуті `requirement_statement_ids`
   та weights (експертний режим).
4. **Public page** (toggle: `use_published_config`) — published_title,
   published_short_desc, published_long_desc, published_salary_display,
   published_experience_display, website_published, process_steps,
   process_time_to_answer, process_days_to_offer.
5. **Application form** — use_forms, form_show_*, form_template_id,
   question_line_ids.
6. **Stages & pipeline** (🆕 нова вкладка) — `stage_config_ids` tree
   із per-stage email/test task/booking + Hidden stages section.
7. **AI & bulk processing** — cv_attachment_ids, bulk_processing_*,
   ai_match_mode, run_ai_match_on_bulk, run_ai_experience_on_bulk.
8. **Tracking & sources** — tracker_ids (зі smart-button).

---

## 7. Що зараз болить рекрутерам (UX-сигнали з docs/коду)

- **«+ Stage» завжди робить глобальну стадію** — баг очікувань
  (див. recruitment_vacancy_stages_flow.md §4).
- **Two-mode "Use published config" toggle** — неочевидно, які поля
  публічні. Дизайн має зняти двозначність.
- **Form-template inheritance** — рекрутер не бачить, що successful'd
  з шаблону, а що override.
- **AI-секція довга й шумна** — стани processing/done/failed зливаються.
- **Test Task — лише one-tick (`add_test_task`)** без можливості задати
  опис per-job (планується).
- **Hidden stages — не існують зараз**; рекрутери просять (PR 3).
- **Booking link для call-стадії — теж новинка** (PR 4).

---

## 8. Куди далі

- Цей файл — твоя робоча карта полів. Можна на ньому ставити
  позначки "в новий дизайн ↑", "сховати", "винести в expert-mode".
- Коли визначишся з групуваннями — синхронимось і я підготую
  імплементаційний план views (`hr_job_views.xml`) у тому самому
  стилі, як у `recruitment_vacancy_stages_flow.md §1`.
- Roadmap PR-ів (PR 1–5) і відкриті питання — у тому ж
  `recruitment_vacancy_stages_flow.md` §5 і §7.
